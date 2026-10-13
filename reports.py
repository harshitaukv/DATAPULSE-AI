import streamlit as st

from components.session import call, can, client
from components.theme import CYAN, EXTRACT, LOAD, QUALITY, TRANSFORM, VALIDATE
from components.ui import card, page_header

c = client()
REPORTS = {
    "pipeline_runs": ("Pipeline runs", "Every execution with status, timings and record counts.", EXTRACT, "🛠️"),
    "data_quality": ("Data quality", "Quality score, its components and anomaly verdict per run.", QUALITY, "⭐"),
    "incidents": ("Incidents", "Every incident with evidence, cause, action and resolution.", TRANSFORM, "🚨"),
    "recovery_audit": ("Recovery audit", "Every automatic and manual recovery attempt with approvals.", LOAD, "🩹"),
}
if can("view_audit"):
    REPORTS["audit_log"] = ("Audit log", "Who did what, when, from where, and the outcome.", VALIDATE, "🔐")

page_header("Reports", "Exports generated from the stored records at the moment you request them.", tone="cyan",
            chips=[(str(len(REPORTS)), "reports available", "#FFFFFF"), ("CSV", "for spreadsheets", LOAD),
                   ("JSON", "for scripts and tools", CYAN)])

cols = st.columns(2)
for n, (kind, (title, description, color, icon)) in enumerate(REPORTS.items()):
    with cols[n % 2], st.container(border=True):
        card(title, description, color, icon, flat=True)
        b1, b2 = st.columns(2)
        for col, fmt in ((b1, "csv"), (b2, "json")):
            key = f"report_{kind}_{fmt}"
            if col.button(f"Prepare {fmt.upper()}", key=f"btn_{key}", width="stretch"):
                st.session_state[key] = call(c.download, f"/api/v1/reports/{kind}", format=fmt)
            if st.session_state.get(key):
                col.download_button(f"Download {fmt.upper()}", st.session_state[key], f"datapulse_{kind}.{fmt}",
                                    "text/csv" if fmt == "csv" else "application/json", key=f"dl_{key}",
                                    width="stretch")
st.caption("Report downloads are recorded in the audit log.")
