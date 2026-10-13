import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.session import call, can, client
from components.charts import donut, show
from components.theme import (ACCENT, BAD, INCIDENT_STATUS_COLORS, LOAD, MUTED, SEVERITY_COLORS, SPECTRUM,
                              EXTRACT, TRANSFORM, VALIDATE, WARN)
from components.ui import (empty_state, esc, fmt_int, nav_link, fmt_time, html_line, incident_status_badge, kv, ledger, page_header,
                           panel, section, severity_badge, short)

ALL = (call(client().get, "/api/v1/incidents", limit=500) or {}).get("items", [])
by_status = pd.Series([i["status"] for i in ALL]).value_counts().to_dict() if ALL else {}
page_header("Incidents", "Problems detected by validation rules, baselines and anomaly detection, with the "
            "measured evidence for each one.", tone="danger",
            chips=[(fmt_int(by_status.get("open", 0)), "open", "#FECDCA"),
                   (fmt_int(by_status.get("under_review", 0)), "under review", WARN),
                   (fmt_int(by_status.get("resolved", 0) + by_status.get("closed", 0)), "resolved or closed", LOAD)])
if ALL:
    sev_all = pd.Series([i["severity"] for i in ALL if i["status"] in ("open", "under_review")]).value_counts().to_dict()
    ledger([dict(v=fmt_int(sev_all.get(s_, 0)), l=f"{s_.title()} open", s=hint, c=SEVERITY_COLORS[s_], icon=ic)
            for s_, hint, ic in (("critical", "stop and fix now", "🔥"), ("high", "fix today", "⚠️"),
                                 ("medium", "plan a fix", "🛠️"), ("low", "keep an eye on it", "👀"))]
           + [dict(v=fmt_int(len(ALL)), l="All incidents", s="every status", c=VALIDATE, icon="🗂️")])
    a, b = st.columns([1, 1.4])
    with a, st.container(border=True):
        show(donut([k.replace("_", " ") for k in by_status], list(by_status.values()),
                   [INCIDENT_STATUS_COLORS.get(k, MUTED) for k in by_status], "By status",
                   center=fmt_int(len(ALL)), sub="incidents", height=260))
    with b, st.container(border=True):
        types = pd.Series([i["incident_type"] for i in ALL]).value_counts().sort_values()
        fig = go.Figure(go.Bar(x=types.values, y=[t.replace("_", " ") for t in types.index], orientation="h",
                               marker=dict(color=[SPECTRUM[k % len(SPECTRUM)] for k in range(len(types))], cornerradius=6),
                               text=types.values, textposition="outside"))
        fig.update_layout(title="By type", height=260, xaxis=dict(visible=False))
        show(fig)
    section("Find an incident", "filter, then select a row", TRANSFORM)
c = client()

f1, f2, f3 = st.columns(3)
status = f1.multiselect("Status", ["open", "under_review", "resolved", "closed"], default=["open", "under_review"])
severity = f2.multiselect("Severity", ["critical", "high", "medium", "low"])
itype = f3.selectbox("Type", ["all", "schema", "data_quality", "volume", "incomplete_input", "transient_failure",
                              "runtime", "repeated_failure", "anomaly", "performance"])
data = call(c.get, "/api/v1/incidents", status=",".join(status) or None, severity=",".join(severity) or None,
            incident_type=None if itype == "all" else itype, limit=200) or {}
items = data.get("items", [])
if not items:
    empty_state("No incidents match these filters", "Clear the filters to see resolved and closed incidents.")
    st.stop()

SEV_ICON = {"critical": "🔴 critical", "high": "🟠 high", "medium": "🟡 medium", "low": "🔵 low"}
table = pd.DataFrame([{"Incident": short(i["id"]), "Severity": SEV_ICON.get(i["severity"], i["severity"]), "Type": i["incident_type"],
                       "Title": i["title"], "Status": i["status"], "Run": short(i["run_id"]),
                       "Created": i["created_at"][:16].replace("T", " ")} for i in items])
event = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun",
                     selection_mode="single-row", height=320)
rows = event.selection.rows if event and event.selection else []
inc = call(c.get, f"/api/v1/incidents/{items[rows[0] if rows else 0]['id']}")
if not inc:
    st.stop()
st.session_state["selected_incident"] = inc["id"]

section("Incident detail", "", SEVERITY_COLORS.get(inc["severity"], MUTED))
with st.container(border=True):
    html_line(f"<h3 style='margin-top:0'>{esc(inc['title'])}</h3>{severity_badge(inc['severity'])} "
              f"{incident_status_badge(inc['status'])} <span style='color:{MUTED};font-size:.85rem'>"
              f"· {esc(inc['rule_id'])} · created {fmt_time(inc['created_at'])}</span>")
    left, right = st.columns([1.15, 1])
    with left:
        html_line(f"<div style='font-weight:800;color:{EXTRACT};margin:.6rem 0 .2rem'>Evidence (measured)</div>")
        ev = inc["evidence"]
        simple = [(k.replace("_", " ").capitalize(), v) for k, v in ev.items() if not isinstance(v, (dict, list))]
        kv(simple)
        nested = {k: v for k, v in ev.items() if isinstance(v, (dict, list))}
        if nested:
            with st.expander("Structured evidence"):
                st.json(nested)
        kv([("Run", short(inc["run_id"])), ("Run status", inc["run_status"]), ("Dataset", inc["dataset_filename"]),
            ("Resolved", fmt_time(inc["resolved_at"]) if inc["resolved_at"] else None)])
    with right:
        panel("Probable cause (hypothesis)", inc["probable_cause"], WARN)
        panel("Recommended action", inc["recommended_action"], LOAD)
        kv([("Recovery policy", inc["recovery_policy"]),
            ("Executable actions", ", ".join(inc["eligible_actions"]) or "none")])
        nav_link("views/analyst.py", "Ask the AI incident analyst about this", "🤖")
    if inc["resolution_notes"]:
        panel("Notes", inc["resolution_notes"], VALIDATE)

if can("update_incident"):
    with st.form("update_incident"):
        html_line(f"<div style='font-weight:800;color:{VALIDATE}'>Update incident</div>")
        statuses = ["open", "under_review", "resolved", "closed"]
        new_status = st.selectbox("Status", statuses, index=statuses.index(inc["status"]))
        note = st.text_area("Resolution note", placeholder="What did you find or change?", max_chars=2000)
        if st.form_submit_button("Save changes", type="primary"):
            body = {"status": new_status}
            if note.strip():
                body["resolution_notes"] = note
            if call(c.patch, f"/api/v1/incidents/{inc['id']}", body):
                st.success("Incident updated.")
                st.rerun()
else:
    st.caption("Viewers can read incidents; engineers and administrators can update them.")
