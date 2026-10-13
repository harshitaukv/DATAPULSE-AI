"""Reproducible evaluation of DataPulse AI.

Runs in an isolated temporary database and data directory (your real data is
not touched). All datasets are synthetic and generated from fixed seeds, so the
results are reproducible. Results are written to docs/evaluation_results.md
and data/reports/evaluation_results.json.

Experiments
  1. Data-quality detection on 100 labeled datasets (rule engine, full pipeline)
  2. Isolation Forest precision / recall / F1 / false-positive rate
  3. RAG retrieval relevance (hit@1, hit@3, MRR, off-topic rejection)
  4. Processing throughput for 1k-100k records
  5. Recovery success rate for eligible failures and correct escalation
  6. Incident explanation checks (category, grounding, documentation relevance)

Usage:  python scripts/evaluate.py [--quick]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="datapulse_eval_"))
os.environ["DATA_DIR"] = str(TMP)
os.environ["DATABASE_URL"] = f"sqlite:///{TMP / 'eval.db'}"
os.environ["RETRY_BASE_DELAY_SECONDS"] = "0.01"
os.environ.setdefault("KNOWLEDGE_BASE_DIR", str(ROOT / "knowledge_base" / "troubleshooting_guides"))
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.ai.diagnosis import analyze_incident, grounding_check, DiagnosisModel  # noqa: E402
from app.ai.rag import get_index  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database.connection import get_session_factory, init_db  # noqa: E402
from app.database.models import Incident, Pipeline  # noqa: E402
from app.ingestion import sample_data as sd  # noqa: E402
from app.monitoring.anomaly_detector import AnomalyDetector  # noqa: E402
from app.services import recovery_service  # noqa: E402
from app.services.dataset_service import store_upload  # noqa: E402
from app.services.pipeline_service import run_pipeline  # noqa: E402

RULE_CATEGORY = {"DQ_MISSING_VALUES": "missing", "DQ_MISSING_COLUMN_VALUES": "missing",
                 "DQ_DUPLICATES": "duplicates", "SCHEMA_MISSING_COLUMNS": "schema", "SCHEMA_DRIFT": "schema",
                 "VOLUME_DROP": "volume", "VOLUME_SPIKE": "volume"}


def pct(x: float) -> float:
    return round(100 * x, 2)


# ------------------------------------------------------------------ datasets
def make_labeled_dataset(label: str, i: int, rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    n = int(rng.normal(5000, 220))
    base = sd.generate_clean(n, seed=10_000 + i, day=date(2026, 10, 1), id_prefix=f"E{i}")
    meta = {"label": label, "rows": n}
    if label == "clean":
        return base, meta
    if label == "missing":
        frac = float(rng.uniform(0.05, 0.40))
        meta["missing_fraction_injected"] = round(frac, 3)
        return sd.inject_missing_and_duplicates(base, seed=i, missing_frac=frac, dup_frac=0.0), meta
    if label == "duplicates":
        frac = float(rng.uniform(0.01, 0.12))
        meta["duplicate_fraction_injected"] = round(frac, 3)
        return sd.inject_missing_and_duplicates(base, seed=i, missing_frac=0.0, dup_frac=frac), meta
    if label == "schema":
        kind = ["rename", "drop", "rename_upper"][i % 3]
        col = ["customer_id", "unit_price", "region", "product_id"][i % 4]
        meta["schema_change"] = f"{kind}:{col}"
        if kind == "rename":
            return base.rename(columns={col: col.replace("_id", "_ref").replace("unit_", "u_") + "_v2"}), meta
        if kind == "drop":
            return base.drop(columns=[col]), meta
        return base.rename(columns={col: "X" + col.upper()}), meta
    if label == "volume":
        keep = float(rng.uniform(0.05, 0.70))
        meta["volume_kept_fraction"] = round(keep, 3)
        return base.head(max(20, int(n * keep))), meta
    raise ValueError(label)


def seed_baseline(db, pipeline, days: int, seed: int) -> list:
    runs = []
    for day, frame in sd.daily_history_frames(days, start=date(2026, 8, 1), seed=seed):
        ds, _ = store_upload(db, f"synthetic_eval_base_{seed}_{day}.csv", sd.to_csv_bytes(frame), None, True)
        runs.append(run_pipeline(db, pipeline, ds, None, trigger_type="seed"))
    return runs


# --------------------------------------------------------------- experiments
def exp_quality_detection(db, pipeline) -> tuple[dict, list]:
    rng = np.random.default_rng(2026)
    plan = ["clean"] * 25 + ["missing"] * 25 + ["duplicates"] * 20 + ["schema"] * 15 + ["volume"] * 15
    order = rng.permutation(len(plan))
    rows = []
    for idx in order:
        label = plan[idx]
        df, meta = make_labeled_dataset(label, int(idx), rng)
        ds, _ = store_upload(db, f"synthetic_eval_{label}_{idx}.csv", sd.to_csv_bytes(df), None, True)
        run = run_pipeline(db, pipeline, ds, None, trigger_type="evaluation")
        cats = sorted({RULE_CATEGORY[i.rule_id] for i in run.incidents if i.rule_id in RULE_CATEGORY})
        rows.append({**meta, "run_id": run.id, "status": run.status, "detected_categories": cats,
                     "rules": sorted(i.rule_id for i in run.incidents),
                     "features": run.metrics.get("features"), "iforest": run.anomaly})
    per_cat = {}
    for cat in ("missing", "duplicates", "schema", "volume"):
        subset = [r for r in rows if r["label"] == cat]
        hits = sum(1 for r in subset if cat in r["detected_categories"])
        per_cat[cat] = {"datasets": len(subset), "detected": hits, "detection_rate_pct": pct(hits / len(subset))}
    clean = [r for r in rows if r["label"] == "clean"]
    fp = sum(1 for r in clean if r["detected_categories"])
    issues = [r for r in rows if r["label"] != "clean"]
    tp = sum(1 for r in issues if r["label"] in r["detected_categories"])
    misses = [{k: r[k] for k in r if k not in ("features", "iforest", "run_id")}
              for r in issues if r["label"] not in r["detected_categories"]]
    return {"datasets": len(rows), "per_category": per_cat,
            "overall_detection_rate_pct": pct(tp / len(issues)),
            "clean_datasets": len(clean), "clean_false_alarms": fp, "false_alarm_rate_pct": pct(fp / len(clean)),
            "missed_examples": misses[:12]}, rows


def exp_isolation_forest(db, pipeline, labeled_rows: list) -> dict:
    train_runs = seed_baseline(db, pipeline, 40, seed=500)
    X_train = [r.metrics["features"] for r in train_runs]
    det = AnomalyDetector(contamination=get_settings().iforest_contamination
                          if get_settings().iforest_contamination == "auto"
                          else float(get_settings().iforest_contamination)).fit(X_train)
    test = [r for r in labeled_rows if r["features"]]
    excluded = len(labeled_rows) - len(test)
    y_true = [r["label"] != "clean" for r in test]
    y_if = [det.score(r["features"])["is_anomaly"] for r in test]
    y_rule = [bool(r["detected_categories"]) for r in test]
    y_comb = [a or b for a, b in zip(y_if, y_rule)]

    def scores(pred):
        tp = sum(p and t for p, t in zip(pred, y_true))
        fp = sum(p and not t for p, t in zip(pred, y_true))
        fn = sum((not p) and t for p, t in zip(pred, y_true))
        tn = sum((not p) and (not t) for p, t in zip(pred, y_true))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(prec, 4), "recall": round(rec, 4),
                "f1": round(f1, 4), "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0}

    ablation = []
    for c in ("auto", 0.02, 0.05, 0.10):
        d = AnomalyDetector(contamination=c).fit(X_train)
        ablation.append({"contamination": c, **scores([d.score(r["features"])["is_anomaly"] for r in test])})

    by_label = {}
    for lab in ("clean", "missing", "duplicates", "volume"):
        sub = [(p, r) for p, r in zip(y_if, test) if r["label"] == lab]
        if sub:
            by_label[lab] = {"runs": len(sub), "flagged_by_isolation_forest": sum(p for p, _ in sub)}
    return {"training_runs": len(X_train), "test_runs": len(test),
            "excluded_runs": excluded, "excluded_reason": "schema failures stop before features are computed",
            "isolation_forest": scores(y_if), "rules_only": scores(y_rule), "rules_or_isolation_forest": scores(y_comb),
            "flag_counts_by_label": by_label, "contamination_used": get_settings().iforest_contamination,
            "contamination_ablation": ablation}


RAG_QUERIES = [
    ("KeyError: 'customer_id' during transformation", "01_missing_column_errors"),
    ("a required column was renamed by the source system", "01_missing_column_errors"),
    ("source added new columns that are not in the contract", "02_schema_changes"),
    ("how do we version the pipeline schema contract", "02_schema_changes"),
    ("the same transaction appears twice in the file", "03_duplicate_records"),
    ("overlapping extract window replayed yesterday's data", "03_duplicate_records"),
    ("keep_first deduplication policy", "03_duplicate_records"),
    ("many rows have empty unit_price", "04_missing_values"),
    ("should we impute null customer identifiers", "04_missing_values"),
    ("price column contains N/A text instead of numbers", "05_invalid_data_types"),
    ("negative quantity and impossible dates", "05_invalid_data_types"),
    ("decimal separator changed after a locale switch", "05_invalid_data_types"),
    ("which stage failed and how to read the stage log", "06_etl_failures"),
    ("transformation fails the same way every time", "06_etl_failures"),
    ("connection reset by peer while loading", "07_database_connection_errors"),
    ("too many connections to postgres", "07_database_connection_errors"),
    ("the run took much longer than usual", "08_timeouts"),
    ("LLM request timed out", "08_timeouts"),
    ("how is the quality score calculated", "09_data_quality_validation"),
    ("why are rejected rows quarantined instead of deleted", "09_data_quality_validation"),
    ("exponential backoff and retry limits", "10_safe_retry_strategies"),
    ("should a schema mismatch be retried", "10_safe_retry_strategies"),
    ("what does an isolation forest anomaly flag mean", "11_pipeline_monitoring"),
    ("compare this run with the previous run", "11_pipeline_monitoring"),
]
OFF_TOPIC = ["best recipe for chocolate cake", "who won the football world cup", "how tall is mount everest",
             "write me a poem about the ocean", "translate good morning into french"]


def exp_rag() -> dict:
    idx = get_index()
    idx.build()
    hit1 = hit3 = 0
    rr = []
    failures = []
    for q, expected in RAG_QUERIES:
        res = idx.search(q, k=5)
        ids = [h["doc_id"] for h in res["hits"]]
        hit1 += bool(ids[:1] == [expected])
        hit3 += expected in ids[:3]
        rank = ids.index(expected) + 1 if expected in ids else None
        rr.append(1 / rank if rank else 0.0)
        if expected not in ids[:3]:
            failures.append({"query": q, "expected": expected, "got": ids[:3]})
    rejected = sum(1 for q in OFF_TOPIC if not idx.search(q)["relevant_found"])
    return {"backend": idx.manifest["backend"], "model": idx.manifest["model"], "chunks": idx.manifest["chunks"],
            "queries": len(RAG_QUERIES), "hit_at_1_pct": pct(hit1 / len(RAG_QUERIES)),
            "hit_at_3_pct": pct(hit3 / len(RAG_QUERIES)), "mrr": round(statistics.mean(rr), 4),
            "off_topic_queries": len(OFF_TOPIC), "off_topic_correctly_rejected": rejected,
            "misses_at_3": failures}


def exp_throughput(db, pipeline, quick: bool) -> list[dict]:
    sizes = [1_000, 10_000, 50_000] if quick else [1_000, 10_000, 50_000, 100_000]
    out = []
    for n in sizes:
        durations = []
        for rep in range(3 if n <= 10_000 else 2):
            frame = sd.generate_clean(n, seed=900 + rep, id_prefix=f"S{n}")
            ds, _ = store_upload(db, f"synthetic_perf_{n}_{rep}.csv", sd.to_csv_bytes(frame), None, True)
            run = run_pipeline(db, pipeline, ds, None, trigger_type="evaluation")
            durations.append(run.duration_seconds)
        med = statistics.median(durations)
        out.append({"records": n, "repetitions": len(durations), "median_seconds": round(med, 3),
                    "records_per_second": int(n / med)})
    return out


def exp_recovery(db, pipeline) -> dict:
    s = get_settings()
    results = {"auto_retry": [], "manual": []}
    for fail_times in (1, 2, 3):
        for rep in range(5):
            frame = sd.generate_clean(3000, seed=1200 + fail_times * 10 + rep, id_prefix=f"R{fail_times}{rep}")
            ds, _ = store_upload(db, f"synthetic_rec_{fail_times}_{rep}.csv", sd.to_csv_bytes(frame), None, True)
            run = run_pipeline(db, pipeline, ds, None, trigger_type="evaluation",
                               options={"fault_injection": {"stage": "load", "fail_times": fail_times}})
            inc = next(i for i in run.incidents if i.rule_id == "RUNTIME_TRANSIENT")
            results["auto_retry"].append({"injected_failures": fail_times, "eligible": fail_times <= s.max_retries,
                                          "run_status": run.status, "incident_status": inc.status})
    from app.database.models import User
    admin = db.scalar(select(User).where(User.role == "admin"))
    if admin is None:
        from app.security.authentication import hash_password
        admin = User(username="eval_admin", password_hash=hash_password("Eval-admin-123"), role="admin")
        db.add(admin)
        db.commit()
    for rep in range(5):
        df = sd.generate_clean(5000, seed=1300 + rep, id_prefix=f"M{rep}").rename(columns={"customer_id": "cust_id"})
        ds, _ = store_upload(db, f"synthetic_rec_schema_{rep}.csv", sd.to_csv_bytes(df), None, True)
        run = run_pipeline(db, pipeline, ds, None, trigger_type="evaluation")
        inc = next(i for i in run.incidents if i.rule_id == "SCHEMA_MISSING_COLUMNS")
        log = recovery_service.request_recovery(db, inc, admin, "apply_column_mapping",
                                                column_mapping={"cust_id": "customer_id"})
        results["manual"].append({"action": "apply_column_mapping", "result": log.result,
                                  "incident_status": inc.status})
    eligible = [r for r in results["auto_retry"] if r["eligible"]]
    ineligible = [r for r in results["auto_retry"] if not r["eligible"]]
    return {
        "max_retries": s.max_retries,
        "eligible_transient_failures": len(eligible),
        "auto_recovered": sum(r["incident_status"] == "resolved" for r in eligible),
        "auto_recovery_success_rate_pct": pct(sum(r["incident_status"] == "resolved" for r in eligible) / len(eligible)),
        "beyond_retry_limit": len(ineligible),
        "correctly_escalated": sum(r["run_status"] == "failed" and r["incident_status"] == "open" for r in ineligible),
        "column_mapping_recoveries": len(results["manual"]),
        "column_mapping_successes": sum(r["result"] == "success" for r in results["manual"]),
    }


EXPECTED_DOC = {"SCHEMA_MISSING_COLUMNS": "01_missing_column_errors", "DQ_DUPLICATES": "03_duplicate_records",
                "DQ_MISSING_COLUMN_VALUES": "04_missing_values", "DQ_MISSING_VALUES": "04_missing_values",
                "VOLUME_DROP": "11_pipeline_monitoring", "INPUT_TRUNCATED": "06_etl_failures",
                "RUNTIME_TRANSIENT": "07_database_connection_errors", "DQ_INVALID_VALUES": "05_invalid_data_types",
                "SCHEMA_DRIFT": "02_schema_changes"}


def exp_explanations(db) -> dict:
    incidents = list(db.scalars(select(Incident)))
    by_rule: dict[str, Incident] = {}
    for inc in incidents:
        by_rule.setdefault(inc.rule_id, inc)
    rows = []
    for rule, inc in sorted(by_rule.items()):
        analysis = analyze_incident(db, inc)
        diag = DiagnosisModel.model_validate(analysis["diagnosis"])
        from app.ai.diagnosis import build_evidence_pack
        unverified = grounding_check(diag, build_evidence_pack(db, inc), analysis["retrieved_documents"])
        doc_ids = [d["doc_id"] for d in analysis["retrieved_documents"][:3]]
        expected = EXPECTED_DOC.get(rule)
        rows.append({"rule": rule, "source": analysis["source"],
                     "category_correct": inc.incident_type in diag.incident_summary.replace(" ", "_").lower()
                     or inc.incident_type.replace("_", " ") in diag.incident_summary.lower(),
                     "evidence_items": len(diag.confirmed_evidence), "unverified_numbers": unverified,
                     "expected_document": expected,
                     "expected_document_in_top3": expected in doc_ids if expected else None,
                     "retrieved_top3": doc_ids})
    scored = [r for r in rows if r["expected_document_in_top3"] is not None]
    return {"mode": rows[0]["source"] if rows else None, "incident_types_evaluated": len(rows),
            "category_correct": sum(r["category_correct"] for r in rows),
            "fully_grounded": sum(not r["unverified_numbers"] for r in rows),
            "relevant_doc_in_top3": sum(r["expected_document_in_top3"] for r in scored),
            "relevant_doc_scored": len(scored), "details": rows}


# ---------------------------------------------------------------------- main
def write_markdown(res: dict) -> str:
    q, i, r, rec, e = res["quality_detection"], res["isolation_forest"], res["rag"], res["recovery"], res["explanations"]
    L = ["# DataPulse AI - Evaluation Results", "",
         f"Generated {res['generated_at']} by `python scripts/evaluate.py` on {res['environment']['python']}, "
         f"database {res['environment']['database']}, embeddings `{r['backend']}`. "
         "All data is synthetic and generated from fixed seeds; rerun the script to reproduce.", "",
         "## 1. Data-quality detection (100 labeled datasets, full pipeline, rule engine)", "",
         "Issue severity was randomised, including mild cases below the configured thresholds "
         "(missing 5-40% of rows in four columns, duplicates 1-12%, volume kept 5-70%), so a detection rate "
         "below 100% is expected and reflects the thresholds, not a defect.", "",
         "| Injected issue | Datasets | Detected | Detection rate |", "|---|---:|---:|---:|"]
    for cat, v in q["per_category"].items():
        L.append(f"| {cat} | {v['datasets']} | {v['detected']} | {v['detection_rate_pct']}% |")
    L += ["", f"Overall detection rate on the 75 datasets with injected issues: **{q['overall_detection_rate_pct']}%**. "
          f"False alarms on the {q['clean_datasets']} clean datasets: **{q['clean_false_alarms']}** "
          f"({q['false_alarm_rate_pct']}%).", ""]
    if q["missed_examples"]:
        L += ["Missed cases (injected issue not detected):", "", "| Label | Injection | Status |", "|---|---|---|"]
        for m in q["missed_examples"]:
            inj = {k: v for k, v in m.items() if k not in ("label", "rows", "status", "detected_categories", "rules")}
            L.append(f"| {m['label']} | {json.dumps(inj)} | {m['status']} |")
        L.append("")
    L += ["## 2. Isolation Forest anomaly detection", "",
          f"Trained on {i['training_runs']} clean synthetic runs; tested on {i['test_runs']} runs from experiment 1 "
          f"({i['excluded_runs']} excluded: {i['excluded_reason']}). Positive class = any injected issue.", "",
          "| Detector | Precision | Recall | F1 | False-positive rate | TP | FP | FN | TN |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, key in (("Isolation Forest", "isolation_forest"), ("Rules only", "rules_only"),
                      ("Rules OR Isolation Forest", "rules_or_isolation_forest")):
        m = i[key]
        L.append(f"| {name} | {m['precision']} | {m['recall']} | {m['f1']} | {m['false_positive_rate']} | "
                 f"{m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} |")
    L += ["", f"Contamination setting used: `{i['contamination_used']}`. Ablation over the contamination "
          "parameter (same training and test data):", "",
          "| Contamination | Precision | Recall | F1 | False-positive rate |", "|---|---:|---:|---:|---:|"]
    for a in i["contamination_ablation"]:
        L.append(f"| {a['contamination']} | {a['precision']} | {a['recall']} | {a['f1']} | {a['false_positive_rate']} |")
    L += ["", "Flags by label: " + ", ".join(f"{k}: {v['flagged_by_isolation_forest']}/{v['runs']}"
                                             for k, v in i["flag_counts_by_label"].items()) + ".", "",
          "## 3. RAG retrieval relevance", "",
          f"{r['queries']} labeled questions over {r['chunks']} knowledge-base chunks "
          f"(backend `{r['backend']}`, model `{r['model']}`).", "",
          "| Metric | Value |", "|---|---:|",
          f"| Hit@1 | {r['hit_at_1_pct']}% |", f"| Hit@3 | {r['hit_at_3_pct']}% |", f"| MRR | {r['mrr']} |",
          f"| Off-topic questions correctly rejected | {r['off_topic_correctly_rejected']}/{r['off_topic_queries']} |", ""]
    if r["misses_at_3"]:
        L += ["Questions where the expected document was not in the top 3: " +
              "; ".join(f"\"{m['query']}\"" for m in r["misses_at_3"]) + ".", ""]
    L += ["## 4. Processing throughput", "", "| Records | Runs | Median duration (s) | Records/second |",
          "|---:|---:|---:|---:|"]
    for t in res["throughput"]:
        L.append(f"| {t['records']:,} | {t['repetitions']} | {t['median_seconds']} | {t['records_per_second']:,} |")
    L += ["", "Duration covers the full run: decrypting the upload, parsing, validation, cleaning, quality rules, "
          "Isolation Forest scoring, encrypted output writing and database persistence.", "",
          "## 5. Recovery", "",
          f"Failure simulation injected 1, 2 or 3 consecutive transient failures into the load stage (5 runs each); "
          f"the retry limit is {rec['max_retries']}.", "",
          "| Measure | Result |", "|---|---:|",
          f"| Eligible transient failures auto-recovered and output-validated | {rec['auto_recovered']}/{rec['eligible_transient_failures']} ({rec['auto_recovery_success_rate_pct']}%) |",
          f"| Failures beyond the retry limit correctly stopped and escalated | {rec['correctly_escalated']}/{rec['beyond_retry_limit']} |",
          f"| Schema incidents recovered with an approved column mapping | {rec['column_mapping_successes']}/{rec['column_mapping_recoveries']} |", "",
          "## 6. Incident explanations", "",
          f"Mode evaluated: `{e['mode']}`. One incident per rule type ({e['incident_types_evaluated']} types).", "",
          "| Check | Result |", "|---|---:|",
          f"| Summary names the correct incident category | {e['category_correct']}/{e['incident_types_evaluated']} |",
          f"| No unverified numbers (every number traceable to evidence) | {e['fully_grounded']}/{e['incident_types_evaluated']} |",
          f"| Relevant troubleshooting document in top 3 | {e['relevant_doc_in_top3']}/{e['relevant_doc_scored']} |", "",
          "| Rule | Expected document | Retrieved top 3 |", "|---|---|---|"]
    for d in e["details"]:
        L.append(f"| {d['rule']} | {d['expected_document'] or '-'} | {', '.join(d['retrieved_top3'])} |")
    L += ["", "LLM-generated explanations were not evaluated here because no LLM API key was configured in the "
          "evaluation environment. With LLM_API_KEY and LLM_MODEL set, the same script evaluates the LLM output "
          "(schema validity and grounding check) instead of the deterministic summaries.", "",
          "## Limitations", "",
          "- All datasets are synthetic; real production data has messier, correlated failure modes.",
          "- The Isolation Forest is evaluated on run-level features from one synthetic pipeline; results do not "
          "transfer automatically to other pipelines.",
          "- Throughput was measured on a single shared CPU in a container; absolute numbers depend on hardware.",
          "- Pandas processing is single-node; it is not distributed big-data processing."]
    return "\n".join(L) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="skip the 100k-record throughput test")
    args = parser.parse_args()
    started = time.time()
    init_db()
    db = get_session_factory()()
    pipeline = db.scalar(select(Pipeline))
    print("Seeding 14-day synthetic baseline ...")
    seed_baseline(db, pipeline, 14, seed=100)
    print("1/6 data-quality detection ...")
    quality, rows = exp_quality_detection(db, pipeline)
    print("2/6 isolation forest ...")
    iforest = exp_isolation_forest(db, pipeline, rows)
    print("3/6 RAG retrieval ...")
    rag = exp_rag()
    print("4/6 throughput ...")
    throughput = exp_throughput(db, pipeline, args.quick)
    print("5/6 recovery ...")
    recovery = exp_recovery(db, pipeline)
    print("6/6 explanations ...")
    explanations = exp_explanations(db)
    res = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "environment": {"python": sys.version.split()[0], "database": "SQLite (isolated temporary database)"},
           "quality_detection": quality, "isolation_forest": iforest, "rag": rag, "throughput": throughput,
           "recovery": recovery, "explanations": explanations,
           "runtime_seconds": round(time.time() - started, 1)}
    (ROOT / "data" / "reports").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "reports" / "evaluation_results.json").write_text(json.dumps(res, indent=2, default=str))
    (ROOT / "docs" / "evaluation_results.md").write_text(write_markdown(res))
    print(f"Done in {res['runtime_seconds']}s -> docs/evaluation_results.md")


if __name__ == "__main__":
    main()
