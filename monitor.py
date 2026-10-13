import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.charts import donut, show
from components.runview import render_run
from components.session import call, client
from components.theme import BAD, CYAN, EXTRACT, LOAD, MUTED, SPECTRUM, STATUS_COLORS, TRANSFORM, VALIDATE, WARN
from components.ui import empty_state, fmt_int, fmt_num, ledger, page_header, section, short

c = client()
f1, f2, f3 = st.session_state.get("mon_status", "all"), st.session_state.get("mon_trigger", "all"), \
    st.session_state.get("mon_limit", 50)
data = call(c.get, "/api/v1/runs", status=None if f1 == "all" else f1, limit=f3) or {}
runs = [r for r in data.get("items", []) if f2 == "all" or r["trigger_type"] == f2]

chips = None
if runs:
    durs = [r["duration_seconds"] for r in runs if r.get("duration_seconds") is not None]
    chips = [(fmt_int(data.get("total", len(runs))), "runs recorded", "#FFFFFF"),
             (fmt_num(sum(durs) / len(durs), 2, " s") if durs else "–", "average duration", CYAN),
             (fmt_int(sum(r["status"] == "failed" for r in runs)), "failed in view", BAD)]
page_header("Pipeline runs", "Every execution with its stages, attempts, record counts and outcome.",
            tone="extract", chips=chips)

a, b, d = st.columns([1, 1, 1])
a.selectbox("Status", ["all", "succeeded", "warning", "failed"], key="mon_status")
b.selectbox("Trigger", ["all", "manual", "recovery", "seed", "evaluation"], key="mon_trigger")
d.selectbox("Show", [25, 50, 100, 250], index=1, key="mon_limit")

if not runs:
    empty_state("No runs match these filters", "Run a pipeline from the Data ingestion page.")
    st.stop()

done = [r for r in runs if r["status"] in ("succeeded", "warning")]
ledger([
    dict(v=fmt_int(len(runs)), l="Runs in view", s=f"of {fmt_int(data.get('total', len(runs)))} recorded", c=EXTRACT, icon="🛠️"),
    dict(v=fmt_num(100 * len(done) / len(runs), 1, "%"), l="Completed", s=f"{len(done)} of {len(runs)}", c=LOAD,
         icon="✅", pct=100 * len(done) / len(runs)),
    dict(v=fmt_int(sum(r["input_records"] or 0 for r in runs)), l="Records read", s="across these runs", c=VALIDATE, icon="📥"),
    dict(v=fmt_int(sum(r["quarantined_records"] or 0 for r in runs)), l="Quarantined", s="held back with reasons",
         c=WARN, icon="🧺"),
    dict(v=fmt_int(sum(r["incident_count"] or 0 for r in runs)), l="Incidents raised", s="by these runs", c=TRANSFORM, icon="🚨"),
])

l, m, r_ = st.columns([1, 1, 1.3])
with l, st.container(border=True):
    counts = pd.Series([r["status"] for r in runs]).value_counts()
    show(donut(list(counts.index), list(counts.values), [STATUS_COLORS.get(s, MUTED) for s in counts.index],
               "Outcome", center=fmt_int(len(runs)), sub="runs", height=260))
with m, st.container(border=True):
    trig = pd.Series([r["trigger_type"] for r in runs]).value_counts()
    show(donut(list(trig.index), list(trig.values), SPECTRUM[:len(trig)], "What started them",
               center=str(len(trig)), sub="triggers", height=260))
with r_, st.container(border=True):
    ordered = list(reversed(runs))
    fig = go.Figure(go.Bar(x=[short(x["id"]) for x in ordered], y=[x["duration_seconds"] or 0 for x in ordered],
                           marker=dict(color=[STATUS_COLORS.get(x["status"], MUTED) for x in ordered], cornerradius=4),
                           hovertemplate="Run %{x}<br>%{y:.2f} s<extra></extra>"))
    fig.update_layout(title="Duration per run (seconds)", height=260, xaxis=dict(showticklabels=False, title="oldest to newest"))
    show(fig)

section("All runs", "select a row to inspect it", EXTRACT)
table = pd.DataFrame([{
    "Run": short(r["id"]), "Status": r["status"], "Started": r["started_at"][:19].replace("T", " "),
    "Dataset": r["dataset_filename"], "Trigger": r["trigger_type"], "Duration (s)": r["duration_seconds"],
    "In": r["input_records"], "Out": r["output_records"], "Quarantined": r["quarantined_records"],
    "Quality": r["quality_score"], "Failed stage": r["failed_stage"], "Incidents": r["incident_count"],
} for r in runs])
STATUS_ICON = {"succeeded": "🟢 succeeded", "warning": "🟠 warning", "failed": "🔴 failed", "running": "🔵 running"}
table["Status"] = table["Status"].map(lambda s: STATUS_ICON.get(s, s))
event = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun",
                     selection_mode="single-row", height=380,
                     column_config={"Quality": st.column_config.ProgressColumn("Quality", min_value=0, max_value=100,
                                                                                format="%.1f", color="#7A5AF8"),
                                    "Duration (s)": st.column_config.NumberColumn(format="%.2f")})
rows = event.selection.rows if event and event.selection else []
selected = runs[rows[0]] if rows else runs[0]
if not rows:
    st.caption("Showing the most recent run. Select a row to inspect a different one.")
detail = call(c.get, f"/api/v1/runs/{selected['id']}")
if detail:
    with st.container(border=True):
        render_run(detail, key=f"mon_{short(detail['id'])}")
