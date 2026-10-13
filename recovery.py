import json
import uuid

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.session import call, can, client
from components.charts import donut, show
from components.theme import EXTRACT, LOAD, MUTED, QUALITY, RESULT_COLORS, TRANSFORM, VALIDATE, WARN
from components.ui import empty_state, fmt_int, html_line, ledger, page_header, section, severity_badge, short

c = client()
policies = call(c.get, "/api/v1/recovery/policies") or {"actions": {}, "approval_required": []}
logs_all = (call(c.get, "/api/v1/recovery-logs", limit=500) or {}).get("items", [])
done = [l for l in logs_all if l["result"] in ("success", "failure")]
ok_n = sum(l["result"] == "success" for l in done)
page_header("Recovery", "Only predefined recovery actions can run. Each one is authorised, audited and followed "
            "by an independent check of the output.", tone="load",
            chips=[(f"{100 * ok_n / len(done):.0f}%" if done else "–", "of executed actions succeeded", "#FFFFFF"),
                   (fmt_int(len(policies.get("actions", {}))), "allowed actions", EXTRACT),
                   (fmt_int(len(policies.get("approval_required", []))), "need admin approval", QUALITY)])

ledger([dict(v=fmt_int(len(logs_all)), l="Recovery records", s="automatic and manual", c=VALIDATE, icon="🗂️"),
        dict(v=fmt_int(sum(l["mode"] == "automatic" for l in logs_all)), l="Automatic actions",
             s="retries, de-duplication", c=EXTRACT, icon="⚙️"),
        dict(v=fmt_int(ok_n), l="Succeeded", s=f"of {len(done)} executed", c=LOAD, icon="✅",
             pct=100 * ok_n / len(done) if done else None),
        dict(v=fmt_int(sum(l["result"] == "requires_manual" for l in logs_all)), l="Escalated",
             s="sent to a person", c=WARN, icon="🧑‍🔧"),
        dict(v=fmt_int(sum(l["approval_status"] == "pending" for l in logs_all)), l="Awaiting approval",
             s="admin decision needed", c=TRANSFORM, icon="⏳")])

if logs_all:
    a, b = st.columns([1.4, 1])
    with a, st.container(border=True):
        df = pd.DataFrame([{"action": l["action"].replace("_", " "), "result": l["result"]} for l in logs_all])
        piv = df.groupby(["action", "result"]).size().unstack(fill_value=0)
        fig = go.Figure()
        for res in piv.columns:
            fig.add_bar(y=piv.index, x=piv[res], name=res.replace("_", " "), orientation="h",
                        marker=dict(color=RESULT_COLORS.get(res, MUTED), cornerradius=4))
        fig.update_layout(barmode="stack", title="Outcome by action", height=270)
        show(fig)
    with b, st.container(border=True):
        modes = pd.Series([l["mode"] for l in logs_all]).value_counts()
        show(donut(list(modes.index), list(modes.values), [EXTRACT, TRANSFORM, QUALITY][:len(modes)], "Who triggered it",
                   center=fmt_int(len(logs_all)), sub="records", height=270))

pending = [l for l in logs_all if l["approval_status"] == "pending"]
if pending:
    section("Awaiting approval", "an administrator decides before these run", TRANSFORM)
    for l in pending:
        with st.container(border=True):
            html_line(f"<b>{l['action']}</b> for incident {short(l['incident_id'])} — {l['incident_title']}<br>"
                      f"<span style='color:{MUTED};font-size:.86rem'>Requested by {l['requested_by_username']} · "
                      f"parameters {json.dumps({k: v for k, v in l['details'].items() if k != 'notes'})}</span>")
            if can("approve_recovery"):
                a, b, _ = st.columns([1, 1, 4])
                reason = st.text_input("Reason (for rejections)", key=f"reason_{l['id']}")
                if a.button("Approve and run", key=f"ap_{l['id']}", type="primary"):
                    with st.spinner("Executing approved recovery…"):
                        r = call(c.post, f"/api/v1/recovery-logs/{l['id']}/decision", {"approve": True})
                    if r:
                        st.success(f"Recovery {r['result']}.")
                        st.rerun()
                if b.button("Reject", key=f"rj_{l['id']}"):
                    if call(c.post, f"/api/v1/recovery-logs/{l['id']}/decision", {"approve": False, "reason": reason}):
                        st.rerun()
            else:
                st.caption("An administrator must approve this request.")

section("Run a recovery action", "choose an open incident and an eligible action", LOAD)
with st.container(border=True):
    open_items = (call(c.get, "/api/v1/incidents", status="open,under_review", limit=200) or {}).get("items", [])
    if not open_items:
        empty_state("No open incidents", "There is nothing to recover right now.")
    else:
        ids = [i["id"] for i in open_items]
        default = ids.index(st.session_state["selected_incident"]) if st.session_state.get("selected_incident") in ids else 0
        labels = {i["id"]: f"{short(i['id'])} · {i['severity']} · {i['title']}" for i in open_items}
        incident_id = st.selectbox("Incident", ids, index=default, format_func=labels.get)
        inc = call(c.get, f"/api/v1/incidents/{incident_id}")
        if inc:
            html_line(f"{severity_badge(inc['severity'])} policy <b>{inc['recovery_policy']}</b> "
                      f"<span style='color:{MUTED};font-size:.86rem'>· {inc['recommended_action']}</span>")
            actions = inc["eligible_actions"]
            if not actions:
                st.info("No executable action is eligible: the retry limit was reached or retries are suspended.")
            elif not can("request_recovery"):
                st.caption("Viewers cannot run recovery actions.")
            else:
                action = st.radio("Action", actions, horizontal=True,
                                  format_func=lambda a: a.replace("_", " ") + (" (needs approval)" if a in policies["approval_required"] else ""))
                st.caption(policies["actions"].get(action, ""))
                body = {"action": action, "idempotency_key": st.session_state.setdefault(f"idem_{incident_id}_{action}", uuid.uuid4().hex)}
                if action == "rerun_with_dataset":
                    datasets = (call(c.get, "/api/v1/uploads", limit=100) or {}).get("items", [])
                    dl = {d["id"]: f"{d['original_filename']} · {fmt_int(d['row_count'])} rows · {d['uploaded_at'][:16].replace('T', ' ')}"
                          for d in datasets}
                    if dl:
                        body["dataset_id"] = st.selectbox("Corrected dataset", list(dl), format_func=dl.get)
                    st.caption("Upload the corrected file on the Data ingestion page first.")
                if action == "apply_column_mapping":
                    suggested = inc["evidence"].get("suggested_mappings") or {}
                    missing = inc["evidence"].get("missing_required") or []
                    mapping = {}
                    for col in missing:
                        guess = next((src for src, info in suggested.items() if info["maps_to"] == col), "")
                        src = st.text_input(f"Source column for '{col}'", value=guess, key=f"map_{incident_id}_{col}")
                        if src:
                            mapping[src] = col
                    body["column_mapping"] = mapping
                body["notes"] = st.text_input("Note for the audit trail", max_chars=300)
                if st.button("Execute action", type="primary"):
                    with st.spinner("Running recovery and validating the output…"):
                        log = call(c.post, f"/api/v1/incidents/{incident_id}/recover", body)
                    st.session_state.pop(f"idem_{incident_id}_{action}", None)
                    if log:
                        if log["approval_status"] == "pending":
                            st.info("Request recorded. An administrator must approve it before it runs.")
                        elif log["result"] == "success":
                            st.success(f"Recovery succeeded and the output was validated (run {short(log['recovery_run_id'])}).")
                        elif log["result"] == "requires_manual":
                            st.info("Incident routed for manual investigation.")
                        else:
                            st.error(f"Recovery did not resolve the incident: {log.get('error_message')}")
                        st.json(log["details"], expanded=False)

section("Recovery history", "every attempt, newest first", VALIDATE)
if not logs_all:
    empty_state("No recovery activity yet", "Automatic retries and manual actions will appear here.")
else:
    st.dataframe(pd.DataFrame([{
        "When": l["executed_at"][:19].replace("T", " "), "Incident": short(l["incident_id"]),
        "Incident title": l["incident_title"], "Action": l["action"], "Mode": l["mode"], "Attempt": l["attempt_number"],
        "Result": {"success": "🟢 success", "failure": "🔴 failure", "requires_manual": "🟠 manual",
                   "pending": "🔵 pending"}.get(l["result"], l["result"]), "Approval": l["approval_status"], "By": l["requested_by_username"],
        "Recovery run": short(l["recovery_run_id"]) if l["recovery_run_id"] else "", "Failure details": l["error_message"],
    } for l in logs_all]), hide_index=True, width="stretch", height=min(36 * (len(logs_all) + 1) + 4, 400))
