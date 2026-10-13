import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.session import call, client
from components.charts import gauge, show
from components.theme import ACCENT, BAD, CYAN, EXTRACT, LOAD, MUTED, QUALITY, TRANSFORM, VALIDATE, WARN, tint
from components.ui import (checks, empty_state, fmt_int, fmt_num, html_line, kv, ledger, page_header, section,
                           short)

c = client()
runs = [r for r in (call(c.get, "/api/v1/runs", limit=200) or {}).get("items", [])]
_sc = [r["quality_score"] for r in runs if r.get("quality_score") is not None]
page_header("Data quality", "Completeness, uniqueness, validity and schema conformance for each run, with the "
            "evidence behind every rejected record.", tone="quality",
            chips=[(fmt_int(len(_sc)), "runs scored", "#FFFFFF"),
                   (fmt_num(sum(_sc) / len(_sc), 1) if _sc else "–", "average score", LOAD),
                   (fmt_int(sum(s_ < 95 for s_ in _sc)), "runs below 95", BAD)])
if not runs:
    empty_state("No runs yet", "Quality metrics appear after the first pipeline run.")
    st.stop()

labels = {r["id"]: f"{short(r['id'])} · {r['status']} · {r['dataset_filename']} · {r['started_at'][:16].replace('T', ' ')}"
          for r in runs}
scored = [r for r in runs if r.get("quality_score") is not None]
first_scored = next((i for i, r in enumerate(runs) if r.get("quality_score") is not None), 0)
run_id = st.selectbox("Run", list(labels), index=first_scored, format_func=labels.get,
                      help="Defaults to the newest run that reached the quality stage.")
q = call(c.get, f"/api/v1/runs/{run_id}/quality", quarantine_rows=50)
if not q:
    st.stop()
m = q.get("metrics") or {}

if q["status"] == "failed" and not m.get("quality_score"):
    st.warning("This run stopped before quality metrics were computed. Its failed checks are listed below.")
else:
    comp = m.get("quality_components", {})
    ledger([dict(v=fmt_num(q["quality_score"]), l="Quality score", s="weighted 30/25/35/10", c=QUALITY, icon="⭐",
                 pct=q["quality_score"]),
            dict(v=fmt_num(100 * comp.get("completeness", 0), 1, "%"), l="Completeness",
                 s=f"{fmt_int(m.get('rows_with_missing_required'))} rows missing values", c=EXTRACT, icon="🧩",
                 pct=100 * comp.get("completeness", 0)),
            dict(v=fmt_num(100 * comp.get("uniqueness", 0), 1, "%"), l="Uniqueness",
                 s=f"{fmt_int(m.get('duplicate_records'))} duplicates", c=VALIDATE, icon="🔁",
                 pct=100 * comp.get("uniqueness", 0)),
            dict(v=fmt_num(100 * comp.get("validity", 0), 1, "%"), l="Validity",
                 s=f"{fmt_int(m.get('invalid_records'))} invalid rows", c=TRANSFORM, icon="🧪",
                 pct=100 * comp.get("validity", 0)),
            dict(v=fmt_num(100 * comp.get("schema_conformance", 0), 0, "%"), l="Schema conformance",
                 s="declared columns present", c=LOAD, icon="📐", pct=100 * comp.get("schema_conformance", 0))])
    g, rd = st.columns([1, 1.3])
    with g, st.container(border=True):
        show(gauge(q["quality_score"], "Score for this run", height=300))
    with rd, st.container(border=True):
        names = ["Completeness", "Uniqueness", "Validity", "Schema conformance"]
        vals = [100 * comp.get(k, 0) for k in ("completeness", "uniqueness", "validity", "schema_conformance")]
        fig = go.Figure(go.Scatterpolar(r=vals + vals[:1], theta=names + names[:1], fill="toself",
                                        fillcolor=tint(VALIDATE, .22), line=dict(color=VALIDATE, width=2.5),
                                        marker=dict(size=9, color=[EXTRACT, VALIDATE, TRANSFORM, LOAD, EXTRACT]),
                                        hovertemplate="%{theta}: %{r:.1f}%<extra></extra>"))
        low = max(0, min(vals) - 10) if vals else 0
        fig.update_layout(title="Quality profile", height=300, showlegend=False,
                          polar=dict(bgcolor=tint(QUALITY, .05), radialaxis=dict(range=[low, 100], gridcolor="#E7E8F3",
                                                                                     tickfont=dict(size=9)),
                                     angularaxis=dict(gridcolor="#E7E8F3")))
        show(fig)

left, right = st.columns([1, 1.2])
with left, st.container(border=True):
    section("Validation checks", "", LOAD)
    checks(q.get("checks", []))
    schema = q.get("schema") or {}
    if schema:
        section("Schema", "", VALIDATE)
        kv([("Missing required", ", ".join(schema.get("missing_required", [])) or "none"),
            ("Unexpected", ", ".join(schema.get("unexpected_columns", [])) or "none"),
            ("Suggested renames", ", ".join(f"{k} → {v['maps_to']}" for k, v in schema.get("suggested_mappings", {}).items()) or "none")])
    base = q.get("baseline") or {}
    if base:
        section("Volume baseline", "", EXTRACT)
        if base.get("status") == "insufficient_history":
            html_line(f"<span style='color:{MUTED}'>Not evaluated: {base['completed_runs']} of {base['required']} "
                      "completed runs available. Volume is never judged without enough history.</span>")
        else:
            kv([("Baseline median records", fmt_int(base.get("baseline_median_records"))),
                ("Runs in baseline", base.get("baseline_runs")), ("Deviation", fmt_num(base.get("deviation_pct"), 1, "%"))])
with right, st.container(border=True):
    missing = {k: v for k, v in (m.get("missing_by_column") or {}).items()}
    if missing and any(missing.values()):
        fig = go.Figure(go.Bar(x=list(missing.values()), y=list(missing.keys()), orientation="h",
                               marker=dict(color=EXTRACT, cornerradius=6), text=list(missing.values()),
                               textposition="outside"))
        fig.update_layout(title="Missing values by column", height=260, yaxis=dict(autorange="reversed"))
        show(fig)
    reasons = q.get("quarantine_summary") or {}
    if reasons:
        items = sorted(reasons.items(), key=lambda kv_: kv_[1], reverse=True)[:10]
        fig = go.Figure(go.Bar(x=[v for _, v in items], y=[k for k, _ in items], orientation="h",
                               marker_color=[BAD if "invalid" in k or "must" in k or "below" in k or "allowed" in k
                                             else WARN for k, _ in items]))
        fig.update_traces(marker_cornerradius=6)
        fig.update_layout(title="Why records were quarantined", height=300, yaxis=dict(autorange="reversed"))
        show(fig)
    if not any(missing.values()) and not reasons:
        empty_state("Nothing quarantined", "Every record in this run passed validation, and no required value was "
                    "missing. Select a run with warnings to see the breakdown here.")

if q.get("transformations"):
    with st.expander("Transformations applied"):
        for t in q["transformations"]:
            st.markdown(f"- {t}")
unusual = {k: v for k, v in (m.get("unusual_values") or {}).items() if v}
if unusual:
    st.caption("Valid but unusual values (kept in the output): " + ", ".join(f"{k}: {v}" for k, v in unusual.items()))

if q.get("quarantine_sample"):
    section("Quarantined records", "a sample of rows held back, with the reason", WARN)
    st.dataframe(pd.DataFrame(q["quarantine_sample"]), hide_index=True, width="stretch", height=280)
    if q.get("records_masked"):
        st.caption(f"Sensitive columns are masked ({', '.join(q['masked_columns'])}). Unmasked records are "
                   "available to administrators and to the engineer who ran the pipeline.")

section("Trends across runs", "share of problem cells and rows in each run", TRANSFORM)
trend = pd.DataFrame((call(c.get, "/api/v1/analytics/trends", days=120) or {}).get("run_series", []))
if not trend.empty:
    with st.container(border=True):
        trend = trend.dropna(subset=["missing_pct"]).reset_index(drop=True)
        fig = go.Figure()
        for col, name, color in (("missing_pct", "Missing cells %", EXTRACT), ("duplicate_pct", "Duplicates %", VALIDATE),
                                 ("invalid_pct", "Invalid rows %", BAD)):
            fig.add_scatter(x=trend.index + 1, y=trend[col], name=name, mode="lines+markers",
                            line=dict(color=color, width=2.5), marker=dict(size=6), fill="tozeroy",
                            fillcolor=tint(color, .08))
        fig.update_layout(height=300, xaxis_title="Run sequence", yaxis_title="%")
        show(fig)
