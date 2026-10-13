import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.session import call, client, user
from components.charts import donut, show
from components.theme import BAD, CYAN, LOAD, ROLE_COLORS, SPECTRUM, TRANSFORM
from components.ui import fmt_int, fmt_time, kv, ledger, page_header

if user().get("role") != "admin":
    page_header("Administration", "Users, audit trail, knowledge base, data retention and recovery policies.")
    st.error("Administrators only.")
    st.stop()
c = client()
users = call(c.get, "/api/v1/users") or []
recent = (call(c.get, "/api/v1/audit-logs", limit=500) or {}).get("items", [])
roles = pd.Series([u["role"] for u in users]).value_counts().to_dict() if users else {}
page_header("Administration", "Users, audit trail, knowledge base, data retention and recovery policies.",
            tone="validate", chips=[(fmt_int(len(users)), "users", "#FFFFFF"),
                                    (fmt_int(sum(u["is_active"] for u in users)), "active", LOAD),
                                    (fmt_int(len(recent)), "recent audit events", TRANSFORM)])
denied = sum(a["outcome"] != "success" for a in recent)
ledger([dict(v=fmt_int(roles.get(r, 0)), l=f"{r.title()}s", s=h, c=ROLE_COLORS[r], icon=i)
        for r, h, i in (("admin", "full control", "🛡️"), ("engineer", "run and recover", "🧑‍💻"),
                        ("viewer", "read only", "👁️"))]
       + [dict(v=fmt_int(len(recent)), l="Audit events", s="latest 500 kept here", c=CYAN, icon="📜"),
          dict(v=fmt_int(denied), l="Not successful", s="denied or failed actions", c=BAD, icon="⛔")])
if recent:
    a_, b_ = st.columns([1.5, 1])
    with a_, st.container(border=True):
        acts = pd.Series([a["action"] for a in recent]).value_counts().head(8).sort_values()
        fig = go.Figure(go.Bar(x=acts.values, y=acts.index, orientation="h", text=acts.values, textposition="outside",
                               marker=dict(color=[SPECTRUM[k % len(SPECTRUM)] for k in range(len(acts))], cornerradius=6)))
        fig.update_layout(title="Most frequent actions", height=280, xaxis=dict(visible=False))
        show(fig)
    with b_, st.container(border=True):
        who = pd.Series([a["username"] or "anonymous" for a in recent]).value_counts().head(5)
        show(donut(list(who.index), list(who.values), SPECTRUM[:len(who)], "Who is active", center=fmt_int(len(who)),
                   sub="people", height=280))
users_tab, audit_tab, kb_tab, retention_tab, policy_tab = st.tabs(
    ["Users", "Audit log", "Knowledge base", "Data retention", "Recovery policies"])

with users_tab:
    RICON = {"admin": "🟣 admin", "engineer": "🔵 engineer", "viewer": "🟢 viewer"}
    st.dataframe(pd.DataFrame([{"Username": u["username"], "Role": RICON.get(u["role"], u["role"]),
                                "Active": u["is_active"]} for u in users]),
                 hide_index=True, width="stretch")
    with st.form("new_user", clear_on_submit=True):
        st.markdown("**Add a user**")
        a, b, r = st.columns(3)
        username = a.text_input("Username")
        password = b.text_input("Password", type="password", help="At least 10 characters with letters and digits or symbols.")
        role = r.selectbox("Role", ["viewer", "engineer", "admin"])
        if st.form_submit_button("Create user", type="primary") and username and password:
            if call(c.post, "/api/v1/users", {"username": username, "password": password, "role": role}):
                st.success(f"Created {role} '{username}'.")
                st.rerun()

with audit_tab:
    f1, f2 = st.columns(2)
    action = f1.text_input("Filter by action", placeholder="e.g. login, run_pipeline, recover_incident")
    who = f2.text_input("Filter by user")
    logs = (call(c.get, "/api/v1/audit-logs", action=action or None, username=who or None, limit=300) or {}).get("items", [])
    st.dataframe(pd.DataFrame([{"Time": fmt_time(a["timestamp"]), "User": a["username"], "Action": a["action"],
                                "Resource": f"{a['resource_type']}:{a['resource_id'][:12]}", "Outcome": a["outcome"],
                                "IP": a["ip_address"], "Details": str(a["details"])[:160]} for a in logs]),
                 hide_index=True, width="stretch", height=420)

with kb_tab:
    status = (call(c.get, "/api/v1/assistant/status") or {}).get("rag", {})
    kv([("Status", "ready" if status.get("ready") else status.get("error", "not ready")),
        ("Embedding backend", status.get("backend")), ("Model", status.get("model")),
        ("Vector store", status.get("vector_store")), ("Documents", status.get("documents")),
        ("Chunks", status.get("chunks")), ("Built", fmt_time(status.get("built_at")))])
    st.caption("The index rebuilds automatically when the markdown files in knowledge_base/ change or the index "
               "files are missing (for example after a host restart).")
    if st.button("Rebuild index now"):
        with st.spinner("Embedding documents…"):
            if call(c.post, "/api/v1/assistant/rebuild-index"):
                st.success("Index rebuilt.")
    q = st.text_input("Test a retrieval query", placeholder="e.g. duplicate transactions")
    if q:
        res = call(c.get, "/api/v1/assistant/search", q=q) or {}
        st.caption(f"Best score {res.get('best_score')} (threshold {res.get('threshold')})")
        for h in res.get("hits", []):
            st.markdown(f"**{h['title']}** · {h['section']} · {h['score']}")
            st.caption(h["text"][:400])

with retention_tab:
    st.markdown("Uploaded files and generated outputs older than the retention period are deleted; run, incident "
                "and audit metadata are kept for traceability.")
    if st.button("Preview retention (dry run)"):
        st.session_state["retention_preview"] = call(c.post, "/api/v1/admin/retention/apply?dry_run=true")
    if prev := st.session_state.get("retention_preview"):
        st.json(prev)
        if st.button("Apply retention now", type="primary"):
            st.json(call(c.post, "/api/v1/admin/retention/apply?dry_run=false"))
            st.session_state.pop("retention_preview", None)

with policy_tab:
    pol = call(c.get, "/api/v1/recovery/policies") or {}
    st.dataframe(pd.DataFrame(pol.get("policies", [])), hide_index=True, width="stretch")
    st.caption("Actions that require administrator approval: " + ", ".join(pol.get("approval_required", [])))
