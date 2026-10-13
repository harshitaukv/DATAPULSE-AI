"""Incident diagnosis.

The evidence pack is assembled exclusively from persisted records (run,
incident, schema report, history) plus retrieved documentation. When an LLM is
configured it receives that pack and must return a JSON object matching
DiagnosisModel. The response is schema-validated and grounding-checked: any
number the model mentions that does not occur in the evidence is reported as
unverified. Without an LLM, a deterministic summary is produced and labelled
as such. The LLM never decides whether a run succeeded.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm_client import LLMClient, LLMUnavailableError
from app.ai.rag import get_index
from app.database.models import Incident, PipelineRun
from app.recovery.policies import ACTIONS, policy_for

logger = logging.getLogger("datapulse.diagnosis")


class DiagnosisModel(BaseModel):
    incident_summary: str = Field(min_length=5, max_length=600)
    confirmed_evidence: list[str] = Field(min_length=1, max_length=10)
    probable_cause: str = Field(min_length=5, max_length=800)
    recommended_action: str = Field(min_length=5, max_length=800)
    uncertainty: str = Field(min_length=3, max_length=600)
    requires_manual_review: bool
    referenced_documents: list[str] = Field(default_factory=list, max_length=6)


SYSTEM_PROMPT = """You are DataPulse AI's incident analyst for data pipelines.
Rules you must follow:
1. Use ONLY the evidence and documentation provided. Never invent log lines, numbers, columns or outcomes.
2. Separate confirmed facts (measured, in the evidence) from hypotheses (probable cause).
3. State uncertainty honestly. Do not output confidence percentages.
4. Never claim a recovery action was executed or succeeded unless the evidence says so.
5. Recommend only these executable actions when relevant: {actions}. Do not output shell commands, code,
   configuration changes or permission changes.
6. Respond with a single JSON object with exactly these keys: incident_summary (string),
   confirmed_evidence (array of short strings quoting measured facts), probable_cause (string),
   recommended_action (string), uncertainty (string), requires_manual_review (boolean),
   referenced_documents (array of document titles you relied on)."""


# ------------------------------------------------------------------ evidence
def confirmed_facts(incident: Incident, run: PipelineRun) -> list[str]:
    """Plain-language facts derived only from stored records (system-verified)."""
    ev = incident.evidence or {}
    facts = [f"Run {run.id[:8]} of pipeline '{run.pipeline.name}' finished with status '{run.status}'."]
    if run.input_records is not None:
        facts.append(f"Input records: {run.input_records:,}.")
    if run.output_records is not None:
        facts.append(f"Output records: {run.output_records:,}; quarantined: {run.quarantined_records or 0:,}.")
    if run.failed_stage:
        facts.append(f"Failed stage: {run.failed_stage} ({run.error_type}): {run.error_message}")
    if ev.get("missing_required"):
        facts.append(f"Missing required columns: {', '.join(ev['missing_required'])}.")
    if ev.get("unexpected_columns"):
        facts.append(f"Unexpected columns received: {', '.join(ev['unexpected_columns'])}.")
    for src, info in (ev.get("suggested_mappings") or {}).items():
        facts.append(f"Column '{src}' resembles expected column '{info['maps_to']}' "
                     f"(name similarity {info['similarity']}).")
    for key, label in (("duplicate_records", "Duplicate records"), ("duplicate_pct", "Duplicate rate %"),
                       ("missing_rows_pct", "Rows missing required values %"), ("missing_pct", "Missing-cell rate %"), ("invalid_records", "Invalid records"),
                       ("invalid_pct", "Invalid-record rate %"), ("baseline_median_records", "Baseline median records"),
                       ("deviation_pct", "Deviation from baseline %"), ("duration_seconds", "Duration (s)")):
        if key in ev:
            facts.append(f"{label}: {ev[key]}.")
    if ev.get("missing_by_column"):
        facts.append("Missing values by column: " + ", ".join(f"{k}={v}" for k, v in ev["missing_by_column"].items()) + ".")
    if ev.get("constraint_violations"):
        facts.append("Constraint violations: " + ", ".join(f"{k}={v}" for k, v in ev["constraint_violations"].items()) + ".")
    if ev.get("type_errors_by_column"):
        facts.append("Type errors: " + ", ".join(f"{k}={v}" for k, v in ev["type_errors_by_column"].items()) + ".")
    if ev.get("truncation"):
        t = ev["truncation"]
        facts.append(f"Final row {t['last_row_index'] + 1} is {t['last_row_missing_fraction'] * 100:.0f}% empty while the "
                     f"rest of the file is {t['body_missing_fraction'] * 100:.2f}% empty.")
    if ev.get("attempts"):
        facts.append(f"Stage '{ev.get('stage')}' attempts: " + ", ".join(
            f"#{a['attempt']} {a['status']}" for a in ev["attempts"]) + ".")
    if ev.get("top_deviating_features"):
        facts.append("Most deviating features: " + ", ".join(
            f"{f['feature']} (z={f['z_score']})" for f in ev["top_deviating_features"]) + ".")
    if ev.get("simulated"):
        facts.append("This failure was produced by the failure-simulation feature (test run).")
    vc = ev.get("volume_check")
    if isinstance(vc, dict) and "deviation_pct" in vc:
        facts.append(f"Volume check: {vc['deviation_pct']}% versus baseline median {vc['baseline_median_records']}.")
    return facts


def similar_incidents(db: Session, incident: Incident, limit: int = 5) -> list[dict]:
    q = (select(Incident).where(Incident.pipeline_id == incident.pipeline_id, Incident.rule_id == incident.rule_id,
                                Incident.id != incident.id)
         .order_by(Incident.created_at.desc()).limit(limit))
    return [{"id": i.id[:8], "created_at": i.created_at.isoformat(), "status": i.status, "title": i.title,
             "resolution_notes": i.resolution_notes} for i in db.scalars(q)]


def previous_run(db: Session, run: PipelineRun) -> PipelineRun | None:
    return db.scalar(select(PipelineRun).where(PipelineRun.pipeline_id == run.pipeline_id,
                                               PipelineRun.started_at < run.started_at,
                                               PipelineRun.id != run.id)
                     .order_by(PipelineRun.started_at.desc()).limit(1))


def build_evidence_pack(db: Session, incident: Incident) -> dict:
    run = incident.run
    schema = (run.report or {}).get("schema") or {}
    pack = {
        "incident": {"id": incident.id[:8], "type": incident.incident_type, "rule": incident.rule_id,
                     "severity": incident.severity, "title": incident.title, "status": incident.status,
                     "evidence": incident.evidence},
        "run": {"id": run.id[:8], "status": run.status, "failed_stage": run.failed_stage, "error_type": run.error_type,
                "error_message": run.error_message, "input_records": run.input_records,
                "output_records": run.output_records, "quarantined_records": run.quarantined_records,
                "quality_score": run.quality_score, "duration_seconds": run.duration_seconds,
                "trigger_type": run.trigger_type},
        "expected_schema": list(run.pipeline.config["columns"]),
        "actual_columns": schema.get("actual_columns") or (incident.evidence or {}).get("actual_columns"),
        "failed_checks": [c for c in (run.report or {}).get("checks", []) if not c.get("passed", True)],
        "recovery_policy": {"name": incident.recovery_policy, "allowed_actions": list(policy_for(incident.rule_id).allowed_actions)},
        "similar_past_incidents": similar_incidents(db, incident),
    }
    return pack


RULE_QUERY_HINTS = {
    "SCHEMA_MISSING_COLUMNS": "missing column error KeyError renamed column mapping schema",
    "SCHEMA_DRIFT": "schema drift unexpected added columns contract",
    "INPUT_TRUNCATED": "truncated incomplete input file partial delivery corrected file",
    "DQ_DUPLICATES": "duplicate records business key deduplication keep_first",
    "DQ_MISSING_VALUES": "missing values null required fields quarantine",
    "DQ_INVALID_VALUES": "invalid data types constraint violations negative quantity price",
    "VOLUME_DROP": "record count dropped volume baseline incomplete extraction",
    "VOLUME_SPIKE": "record count spike volume baseline overlapping extract",
    "PERF_SLOW_RUN": "slow run timeout duration",
    "ML_ANOMALY": "anomaly detection isolation forest unusual run metrics",
    "RUNTIME_TRANSIENT": "database connection reset transient retry backoff",
    "RUNTIME_STAGE_FAILURE": "ETL stage failure transformation error logs",
    "REPEATED_FAILURE": "repeated failures retries suspended manual review",
}


def incident_query(incident: Incident) -> str:
    ev = incident.evidence or {}
    extra = " ".join(str(x) for x in (ev.get("missing_required") or []))
    hint = RULE_QUERY_HINTS.get(incident.rule_id, incident.incident_type.replace("_", " "))
    return f"{hint} {incident.title} {incident.run.error_message or ''} {extra}".strip()


# ------------------------------------------------------------------ analysis
def _numbers(text: str) -> set[str]:
    """Standalone numbers only: digits embedded in identifiers (e.g. run id 'e3b1794c') are ignored."""
    return {n.replace(",", "") for n in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])", text)}


def grounding_check(diagnosis: DiagnosisModel, pack: dict, docs: list[dict]) -> list[str]:
    source = json.dumps(pack, default=str) + " ".join(d["text"] for d in docs)
    allowed = _numbers(source)
    allowed |= {str(int(float(x))) for x in allowed if re.fullmatch(r"\d+\.\d+", x)}
    produced = _numbers(" ".join([diagnosis.incident_summary, *diagnosis.confirmed_evidence,
                                  diagnosis.probable_cause, diagnosis.recommended_action]))
    return sorted(n for n in produced if n not in allowed and len(n) > 1)


def deterministic_diagnosis(incident: Incident, facts: list[str], docs: list[dict], similar: list[dict]) -> dict:
    policy = policy_for(incident.rule_id)
    doc_titles = sorted({d["title"] for d in docs})
    uncertainty = ("This summary is rule-based: facts are measured, while the probable cause is the standard "
                   "explanation for this incident type and should be confirmed with the source owner.")
    if similar:
        uncertainty += f" {len(similar)} similar incident(s) occurred before on this pipeline."
    return DiagnosisModel(
        incident_summary=f"{incident.severity.title()} {incident.incident_type.replace('_', ' ')} incident: {incident.title}.",
        confirmed_evidence=facts[:10], probable_cause=policy.probable_cause,
        recommended_action=policy.recommended_action + f" Executable actions: {', '.join(policy.allowed_actions)}.",
        uncertainty=uncertainty,
        requires_manual_review=incident.severity in ("high", "critical") or incident.status == "open",
        referenced_documents=doc_titles[:6]).model_dump()


def analyze_incident(db: Session, incident: Incident, client: LLMClient | None = None) -> dict:
    client = client or LLMClient()
    run = incident.run
    facts = confirmed_facts(incident, run)
    pack = build_evidence_pack(db, incident)
    retrieval = get_index().search(incident_query(incident))
    docs = retrieval["hits"]
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "system_confirmed_facts": facts,
              "retrieved_documents": docs, "retrieval": {k: retrieval[k] for k in
                                                         ("backend", "threshold", "relevant_found", "best_score")}}
    if client.configured:
        try:
            docs_text = "\n\n".join(f"[{d['title']} / {d['section']}]\n{d['text']}" for d in docs) or "(none relevant)"
            user_msg = (f"EVIDENCE (from the pipeline database):\n{json.dumps(pack, default=str, indent=1)}\n\n"
                        f"RETRIEVED DOCUMENTATION:\n{docs_text}\n\nReturn the JSON object now.")
            raw = client.complete(SYSTEM_PROMPT.format(actions=", ".join(ACTIONS)), user_msg, json_mode=True)
            parsed = DiagnosisModel.model_validate(_parse_json(raw))
            result.update({"source": "llm", "model": client.model, "diagnosis": parsed.model_dump(),
                           "unverified_numbers": grounding_check(parsed, pack, docs)})
            return result
        except (LLMUnavailableError, ValidationError, ValueError) as exc:
            logger.warning("LLM diagnosis unavailable: %s", exc)
            result["llm_error"] = _short_error(exc)
    result.update({"source": "deterministic_fallback", "model": None,
                   "diagnosis": deterministic_diagnosis(incident, facts, docs, pack["similar_past_incidents"]),
                   "unverified_numbers": []})
    if not client.configured:
        result["llm_status"] = "not_configured"
    return result


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("LLM response did not contain a JSON object")
    return json.loads(text[start:end + 1])


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return f"LLM response failed schema validation ({exc.error_count()} error(s)); deterministic summary used."
    return str(exc)[:300]
