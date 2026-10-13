import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.charts import donut, gauge, show
from components.session import call, client
from components.theme import (BAD, CYAN, EXTRACT, LOAD, MUTED, OK, QUALITY, SEVERITY_COLORS, SPECTRUM, STATUS_COLORS,
                              TRANSFORM, VALIDATE, WARN, tint)
from components.ui import (empty_state, esc, feed_row, nav_link, fmt_int, fmt_num, fmt_time, html_line, ledger, page_header,
                           section, severity_badge, short, stage_flow, stage_track_html, status_badge)

c = client()
ov = call(c.get, "/api/v1/analytics/overview", include_seed=st.session_state.get("ov_seed", True))
chips = None
if ov and ov["total_runs"]:
    chips = [(fmt_num(ov["success_rate"], 1, "%"), "of runs completed", LOAD),
             (fmt_int(ov["open_incidents"]), "open incidents", BAD if ov["open_incidents"] else LOAD),
             (fmt_int(ov["pending_approvals"]), "awaiting approval", QUALITY)]
page_header("Overview", "Health of every pipeline run, incident and recovery recorded by the platform.",
            tone="validate", chips=chips)

include_seed = st.toggle("Include synthetic baseline runs", value=True, key="ov_seed",
                         help="Baseline runs were produced by scripts/seed_database.py on synthetic data.")
if ov is None:
    st.stop()
if not ov["total_runs"]:
    empty_state("No pipeline runs yet",
                "Open Data ingestion, upload a CSV or JSON file (or use a synthetic sample) and run the pipeline.")
    st.stop()

ledger([
    dict(v=fmt_int(ov["total_runs"]), l="Pipeline runs", s=f"{fmt_int(ov['records_processed'])} records processed",
         c=EXTRACT, icon="🛠️"),
    dict(v=fmt_num(ov["success_rate"], 1, "%"), l="Completed", s=f"{ov['succeeded']} clean · {ov['warnings']} with warnings",
         c=LOAD, icon="✅", pct=ov["success_rate"]),
    dict(v=fmt_int(ov["failed"]), l="Failed runs", s=f"{100 * ov['failed'] / ov['total_runs']:.1f}% of all runs",
         c=BAD, icon="⛔", pct=100 * ov["failed"] / ov["total_runs"]),
    dict(v=fmt_int(ov["open_incidents"]), l="Open incidents",
         s=", ".join(f"{v} {k}" for k, v in ov["open_incidents_by_severity"].items()) or "none", c=TRANSFORM, icon="🚨"),
    dict(v=fmt_num(ov["average_quality_score"], 1), l="Average quality score", s="out of 100", c=QUALITY, icon="⭐",
         pct=ov["average_quality_score"]),
    dict(v=fmt_num(ov["recovery_success_rate"], 1, "%") if ov["recovery_success_rate"] is not None else "–",
         l="Recovery success", s=f"{ov['recovery_successes']} of {ov['recovery_attempts']} attempts", c=VALIDATE,
         icon="🩹", pct=ov["recovery_success_rate"]),
])
if ov["pending_approvals"]:
    st.warning(f"{ov['pending_approvals']} recovery request(s) are waiting for administrator approval.")

trends = call(c.get, "/api/v1/analytics/trends", days=90) or {}
series = pd.DataFrame(trends.get("run_series", []))
if not include_seed and not series.empty:
    series = series[series["trigger_type"] != "seed"]
run_list = [r for r in (call(c.get, "/api/v1/runs", limit=250) or {}).get("items", [])
            if include_seed or r["trigger_type"] != "seed"]

# ------------------------------------------------------------ stage strip
fails = pd.Series([r["failed_stage"] for r in run_list if r.get("failed_stage")]).value_counts().to_dict()
qs = [r["quality_score"] for r in run_list if r.get("quality_score") is not None]


def _fail(stage: str) -> str:
    n = fails.get(stage, 0)
    col = BAD if n else OK
    return f"<b style='color:{col}'>{n}</b> failed here"


section("Where runs break", "every run moves left to right through these five stages", VALIDATE)
stage_flow({
    "extract": ("Reads CSV or JSON and normalises headers", f"<b>{len(run_list)}</b> started · {_fail('extract')}"),
    "validate": ("Checks the contract, types and constraints", _fail("validate")),
    "transform": ("Coerces types, de-duplicates, derives columns", _fail("transform")),
    "quality": ("Scores completeness, uniqueness, validity",
                f"avg <b>{sum(qs) / len(qs):.1f}</b> · {_fail('quality')}" if qs else _fail("quality")),
    "load": ("Writes clean output, quarantines rejects",
             f"<b>{fmt_int(sum(r['output_records'] or 0 for r in run_list))}</b> rows out · "
             f"<b style='color:{WARN}'>{fmt_int(sum(r['quarantined_records'] or 0 for r in run_list))}</b> held"),
})

# ------------------------------------------------------------ status, score, severity
sev = trends.get("incidents_by_severity", {})
a, b, d = st.columns([1.05, 1, 1.05])
with a, st.container(border=True):
    stat = [(k, ov[key]) for k, key in (("succeeded", "succeeded"), ("warning", "warnings"), ("failed", "failed"))]
    show(donut([k for k, _ in stat], [v for _, v in stat], [STATUS_COLORS[k] for k, _ in stat], "Run outcomes",
               center=fmt_int(ov["total_runs"]), sub="runs"))
with b, st.container(border=True):
    show(gauge(ov["average_quality_score"], "Average quality score", height=290))
with d, st.container(border=True):
    order = [s for s in ("critical", "high", "medium", "low") if s in sev]
    if order:
        show(donut(order, [sev[s] for s in order], [SEVERITY_COLORS[s] for s in order], "Incidents by severity",
                   center=fmt_int(sum(sev.values())), sub="incidents"))
    else:
        empty_state("No incidents", "Every run so far passed its checks.")

# ------------------------------------------------------------ activity + attention
left, right = st.columns([1.35, 1])
with left, st.container(border=True):
    per_day = pd.DataFrame(trends.get("runs_per_day", []))
    if len(per_day) >= 2:
        fig = go.Figure()
        for status in ("succeeded", "warning", "failed"):
            if status in per_day:
                fig.add_bar(x=per_day["date"], y=per_day[status], name=status, marker_color=STATUS_COLORS[status])
        fig.update_layout(barmode="stack", title="Runs per day", height=360, bargap=0.35)
        show(fig)
    elif not series.empty:
        dser = series.dropna(subset=["duration_seconds"]).reset_index(drop=True)
        fig = go.Figure(go.Scatter(x=dser.index + 1, y=dser["duration_seconds"], mode="lines+markers", fill="tozeroy",
                                   line=dict(color=CYAN, width=2.5), fillcolor=tint(CYAN, .15),
                                   marker=dict(size=8, color=dser["status"].map(STATUS_COLORS).fillna(MUTED),
                                               line=dict(color="#FFFFFF", width=1.5)),
                                   customdata=dser["run_id"].str[:8],
                                   hovertemplate="Run %{customdata}<br>%{y:.2f} s<extra></extra>"))
        fig.update_layout(title="Duration by run (seconds)", height=360, xaxis_title="Run sequence")
        show(fig)
with right, st.container(border=True):
    html_line(f"<div class='dp-sec' style='--c:{TRANSFORM};margin-top:.2rem'><span class='dot'></span>"
              f"<h3>Needs attention</h3></div>")
    open_inc = (call(c.get, "/api/v1/incidents", status="open,under_review", limit=5) or {}).get("items", [])
    if not open_inc:
        empty_state("All clear", "No incident is open right now.")
    else:
        html_line("".join(feed_row(esc(i["title"]),
                                   f"{severity_badge(i['severity'])} &nbsp;{esc(i['incident_type'].replace('_', ' '))}"
                                   f" · run {short(i['run_id'])}",
                                   SEVERITY_COLORS.get(i["severity"], MUTED)) for i in open_inc))
        nav_link("views/incidents.py", "Open the incident list", "🚨")

# ------------------------------------------------------------ per-run trends
if not series.empty:
    q = series.dropna(subset=["quality_score"]).reset_index(drop=True)
    left, mid, right = st.columns(3)
    with left, st.container(border=True):
        fig = go.Figure(go.Scatter(x=q.index + 1, y=q["quality_score"], mode="lines+markers", fill="tozeroy",
                                   line=dict(color=VALIDATE, width=2.5, shape="spline"), fillcolor=tint(VALIDATE, .12),
                                   marker=dict(size=7, color=TRANSFORM, line=dict(color="#FFFFFF", width=1.5)),
                                   customdata=q["run_id"].str[:8],
                                   hovertemplate="Run %{customdata}<br>%{y:.1f}<extra></extra>"))
        fig.update_layout(title="Quality score by run", height=280, xaxis_title="Run sequence",
                          yaxis=dict(range=[min(50, q["quality_score"].min() - 5), 101]))
        show(fig)
    with mid, st.container(border=True):
        n = series.dropna(subset=["input_records"]).reset_index(drop=True)
        colors = n["status"].map(STATUS_COLORS).fillna(MUTED)
        fig = go.Figure(go.Bar(x=n.index + 1, y=n["input_records"], marker=dict(color=colors, cornerradius=4),
                               customdata=n["run_id"].str[:8],
                               hovertemplate="Run %{customdata}<br>%{y:,} records<extra></extra>"))
        fig.update_layout(title="Input records by run", height=280, xaxis_title="Run sequence")
        show(fig)
    with right, st.container(border=True):
        types = trends.get("incidents_by_type", {})
        if types:
            items = sorted(types.items(), key=lambda kv: kv[1])
            fig = go.Figure(go.Bar(x=[v for _, v in items], y=[k.replace("_", " ") for k, _ in items], orientation="h",
                                   marker=dict(color=[SPECTRUM[i % len(SPECTRUM)] for i in range(len(items))],
                                               cornerradius=6), text=[v for _, v in items], textposition="outside"))
            fig.update_layout(title="Incidents by type", height=280, xaxis=dict(visible=False))
            show(fig)
        else:
            empty_state("No incidents", "Every run so far passed its checks.")

# ------------------------------------------------------------ latest runs
section("Latest runs", "stage by stage, newest first", EXTRACT)
with st.container(border=True):
    runs = (call(c.get, "/api/v1/runs", limit=6) or {}).get("items", [])
    for idx, r in enumerate(runs):
        run_detail = call(c.get, f"/api/v1/runs/{r['id']}", quiet=True) or {}
        cols = st.columns([1.5, 3.2, 1.2], vertical_alignment="center")
        with cols[0]:
            html_line(f"<b>{short(r['id'])}</b> {status_badge(r['status'])}<br>"
                      f"<span style='color:{MUTED};font-size:.8rem'>{fmt_time(r['started_at'])} · "
                      f"{esc(r['dataset_filename'] or '')}</span>")
        with cols[1]:
            html_line(stage_track_html(run_detail.get("stage_log", []), compact=True))
        with cols[2]:
            html_line(f"<span style='font-size:.84rem'><b>{fmt_int(r['input_records'])}</b> in · "
                      f"<b>{fmt_int(r['output_records'])}</b> out<br>quality <b>{fmt_num(r['quality_score'])}</b>"
                      f"{' · ' + str(r['incident_count']) + ' incident(s)' if r['incident_count'] else ''}</span>")
        if idx < len(runs) - 1:
            html_line(f"<div style='border-top:1px solid #ECEEF7;margin:.1rem 0'></div>")
