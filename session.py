"""Session state, authentication gate and shared API access."""
from __future__ import annotations

import streamlit as st

from api_client import API_BASE_URL, APIClient, APIError


def client() -> APIClient:
    return APIClient(st.session_state.get("token"))


def user() -> dict:
    return st.session_state.get("user") or {}


def can(permission: str) -> bool:
    return permission in user().get("permissions", [])


def call(fn, *args, default=None, quiet: bool = False, **kwargs):
    """Run an API call, turning failures into readable messages instead of tracebacks."""
    try:
        return fn(*args, **kwargs)
    except APIError as exc:
        if exc.status == 401:
            logout(message="Your session expired. Sign in again.")
        if not quiet:
            st.error(exc.message)
        return default


def logout(message: str | None = None) -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    if message:
        st.session_state["login_message"] = message
    st.rerun()


def login_screen() -> None:
    from components.theme import STAGE_COLORS, tint
    from components.ui import BRAND_HTML, _PULSE

    st.markdown("<div style='height:5vh'></div>", unsafe_allow_html=True)
    left, gap, right = st.columns([1.25, .08, 1])
    with left:
        stages = "".join(f'<span class="dp-chip" style="--c:{c}"><i></i>{n.title()}</span>' for n, c in STAGE_COLORS.items())
        caps = [("🧪", "Five-stage ETL with per-stage retries and a quarantine for rejected rows"),
                ("📈", "Quality score, volume baselines and Isolation Forest anomaly detection"),
                ("🤖", "AI incident analyst grounded in run evidence and a troubleshooting knowledge base"),
                ("🛡️", "Recovery limited to predefined, audited and approval-gated actions")]
        cap_html = "".join(f'<div style="display:flex;gap:.7rem;align-items:flex-start;margin:.55rem 0;position:relative;z-index:1">'
                           f'<span style="width:34px;height:34px;flex:none;border-radius:10px;display:grid;place-items:center;'
                           f'background:rgba(255,255,255,.12)">{i}</span><span style="color:rgba(255,255,255,.88);'
                           f'font-size:.92rem;padding-top:.4rem">{t}</span></div>' for i, t in caps)
        st.markdown(
            f'<div class="dp-hero" style="--mid:#4A2DB8;--hi:#EE46BC;padding:2rem 2rem 4.2rem 2rem">'
            f'<span class="orb" style="width:260px;height:260px;right:-60px;top:-90px;background:{tint("#EE46BC", .4)}"></span>'
            f'<span class="orb" style="width:180px;height:180px;left:40%;bottom:-100px;background:{tint("#2E90FA", .35)}"></span>'
            f'<svg class="pulse" viewBox="0 0 600 160" preserveAspectRatio="none" aria-hidden="true" '
            f'style="top:auto;bottom:0;height:16%;width:100%;right:0;opacity:.7">'
            f'<path class="glow" d="{_PULSE}" vector-effect="non-scaling-stroke"/>'
            f'<path d="{_PULSE}" vector-effect="non-scaling-stroke"/></svg>'
            f'<div style="position:relative;z-index:1">{BRAND_HTML}</div>'
            f'<h1 style="font-size:2.3rem;line-height:1.15;margin-top:1.4rem;max-width:16ch">Know why a pipeline broke, '
            f'and fix it safely.</h1>'
            f'<p>Monitor every run, see the evidence behind each incident, and recover through audited actions.</p>'
            f'<div class="dp-chips" style="margin-top:1.2rem">{stages}</div>'
            f'<div style="margin-top:1.4rem">{cap_html}</div></div>', unsafe_allow_html=True)
    with right:
        st.markdown("<div style='height:4.5rem'></div>"
                    "<h2 style='margin-bottom:.2rem'>Sign in</h2>"
                    "<p style='color:#625D85;margin-top:0'>Use the account your administrator created for you.</p>",
                    unsafe_allow_html=True)
        if msg := st.session_state.pop("login_message", None):
            st.info(msg)
        with st.form("login", border=True):
            username = st.text_input("Username", autocomplete="username")
            password = st.text_input("Password", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
        if submitted:
            if not username or not password:
                st.error("Enter your username and password.")
                return
            try:
                result = APIClient().login(username, password)
            except APIError as exc:
                st.error(exc.message)
                return
            st.session_state["token"] = result["access_token"]
            st.session_state["user"] = result["user"]
            st.rerun()
        roles = "".join(f'<div style="display:flex;gap:.6rem;align-items:center;margin:.35rem 0;font-size:.86rem">'
                        f'<span class="dp-badge" style="--c:{c};--t:{tint(c, .14)}">{r}</span>'
                        f'<span style="color:#625D85">{d}</span></div>'
                        for r, c, d in (("viewer", "#12B76A", "reads dashboards, incidents and reports"),
                                        ("engineer", "#2E90FA", "uploads data, runs pipelines, requests recovery"),
                                        ("admin", "#EE46BC", "approves recovery, manages users and audit")))
        st.markdown(f"<div style='margin-top:1rem'>{roles}</div>", unsafe_allow_html=True)
        st.caption(f"Backend: {API_BASE_URL}")
