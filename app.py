"""DataPulse AI dashboard (Streamlit).

Run from the frontend folder:  streamlit run app.py
The backend URL is read from API_BASE_URL (default http://localhost:8000).
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

st.set_page_config(page_title="DataPulse AI", page_icon="💜", layout="wide", initial_sidebar_state="auto")

from components.session import call, client, login_screen, logout, user  # noqa: E402
from components.theme import (ACCENT, BAD, EXTRACT, NEUTRAL, OK, QUALITY, ROLE_COLORS, VALIDATE,  # noqa: E402
                              apply_theme)
from components.ui import esc, html_line  # noqa: E402

apply_theme()

if "token" not in st.session_state:
    login_screen()
    st.stop()

u = user()
ASSETS = Path(__file__).parent / "assets"
st.logo(str(ASSETS / "logo.svg"), size="large", icon_image=str(ASSETS / "icon.svg"))
pages = {
    "Monitor": [
        st.Page("views/overview.py", title="Overview", icon="🏠", default=True),
        st.Page("views/ingestion.py", title="Data ingestion", icon="📥"),
        st.Page("views/monitor.py", title="Pipeline runs", icon="🛠️"),
        st.Page("views/quality.py", title="Data quality", icon="✅"),
    ],
    "Investigate": [
        st.Page("views/incidents.py", title="Incidents", icon="🚨"),
        st.Page("views/analyst.py", title="AI incident analyst", icon="🤖"),
        st.Page("views/recovery.py", title="Recovery", icon="🩹"),
        st.Page("views/reports.py", title="Reports", icon="📊"),
    ],
}
if u.get("role") == "admin":
    pages["Administer"] = [st.Page("views/admin.py", title="Administration", icon="🔐")]

nav = st.navigation(pages)

with st.sidebar:
    role = u.get("role", "viewer")
    rc = ROLE_COLORS.get(role, ACCENT)
    status = call(client().get, "/api/v1/assistant/status", quiet=True) or {}
    llm = status.get("llm", {})
    rag = status.get("rag", {})
    html_line(f'<div class="dp-user" style="--c:{rc}"><div class="dp-avatar">{esc(u.get("username", "?")[:1].upper())}</div>'
              f'<div><div class="u">{esc(u.get("username"))}</div><div class="r">{esc(role)}</div></div></div>')
    sys_rows = [
        ("Backend", "online" if status else "unreachable", OK if status else BAD),
        ("Assistant", f"LLM · {llm.get('model')}" if llm.get("configured") else "rule-based", VALIDATE if llm.get("configured") else QUALITY),
        ("Retrieval", f"{rag.get('backend')} · {rag.get('chunks')} chunks" if rag.get("ready") else "not ready",
         EXTRACT if rag.get("ready") else NEUTRAL),
    ]
    html_line('<div class="dp-sys">' + "".join(f'<div style="--c:{c}"><i></i>{k}<b>{esc(v)}</b></div>'
                                               for k, v, c in sys_rows) + "</div>")
    if st.button("Sign out", width="stretch"):
        logout()

nav.run()
