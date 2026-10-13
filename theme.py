"""Visual system.

Colour carries meaning here: every ETL stage owns one hue, and the same hues are
reused wherever that stage (or the outcome it produces) appears. Statuses use the
usual traffic-light semantics. A deep-indigo "night" anchors the sidebar and the
page heroes, and a hand-drawn pulse line is the recurring brand mark.
"""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# ---------------------------------------------------------------- core tokens
NIGHT = "#1B1640"      # sidebar, hero base, headings
INK = "#1B1640"
MUTED = "#625D85"
LINE = "#E1E3F2"
SURFACE = "#F5F6FC"
CARD = "#FFFFFF"
ACCENT = "#6E4BF2"     # primary actions

# Stage spectrum: Extract → Validate → Transform → Quality → Load
EXTRACT = "#2E90FA"
VALIDATE = "#7A5AF8"
TRANSFORM = "#EE46BC"
QUALITY = "#EAAA08"
LOAD = "#12B76A"
CYAN = "#06AED4"
STAGE_COLORS = {"extract": EXTRACT, "validate": VALIDATE, "transform": TRANSFORM, "quality": QUALITY, "load": LOAD}
SPECTRUM = [EXTRACT, VALIDATE, TRANSFORM, QUALITY, LOAD, CYAN]

# Semantics
OK = "#12B76A"
WARN = "#F79009"
BAD = "#F04438"
INFO = "#2E90FA"
NEUTRAL = "#98A2B3"

STATUS_COLORS = {"succeeded": OK, "warning": WARN, "failed": BAD, "running": INFO, "queued": NEUTRAL}
SEVERITY_COLORS = {"low": "#06AED4", "medium": "#EAAA08", "high": "#F79009", "critical": BAD}
INCIDENT_STATUS_COLORS = {"open": BAD, "under_review": WARN, "resolved": OK, "closed": NEUTRAL}
RESULT_COLORS = {"success": OK, "failure": BAD, "pending": INFO, "skipped": NEUTRAL, "requires_manual": WARN}
ROLE_COLORS = {"admin": TRANSFORM, "engineer": EXTRACT, "viewer": LOAD}

# Hero tones: (mid colour, bright end). Each page takes the hue of what it is about.
TONES = {
    "extract": ("#1849A9", EXTRACT), "validate": ("#4A2DB8", VALIDATE), "transform": ("#9E1A7A", TRANSFORM),
    "quality": ("#93370D", "#F5A40C"), "load": ("#05603A", LOAD), "cyan": ("#0E5D73", CYAN),
    "danger": ("#912018", "#F97066"),
}


def tint(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


CSS = f"""
<style>
/* ---------- canvas & type ---------- */
.stApp {{ background:
    radial-gradient(1200px 500px at 100% -10%, {tint(VALIDATE, .07)}, transparent 60%),
    radial-gradient(900px 420px at -10% 110%, {tint(EXTRACT, .06)}, transparent 60%),
    {SURFACE}; color: {INK}; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 4rem; max-width: 1340px; }}
h1, h2, h3, h4 {{ color: {INK}; letter-spacing: -0.015em; }}
h3 {{ font-weight: 650; font-size: 1.12rem; margin-top: 1.2rem; }}
.stMain p, .stMain li, .stMain label {{ color: {INK}; }}
[data-testid="stCaptionContainer"], .stCaption {{ color: {MUTED}; }}
html, body, .stApp {{ font-feature-settings: "tnum" 1; }}

/* ---------- sidebar ---------- */
section[data-testid="stSidebar"] {{
  background: linear-gradient(185deg, #241C58 0%, {NIGHT} 45%, #120E2E 100%); }}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] {{ border-radius: 10px; margin: 1px 0; }}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover {{ background: rgba(255,255,255,.06); }}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: linear-gradient(90deg, {tint(VALIDATE, .55)}, {tint(TRANSFORM, .25)}); }}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] span,
section[data-testid="stSidebar"] .stButton p {{ color: #E9E6FF !important; }}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] span {{ color: #FFFFFF !important; font-weight: 700; }}
section[data-testid="stSidebar"] [data-testid="stSidebarNavSeparator"] {{ border-color: rgba(255,255,255,.12); }}
section[data-testid="stSidebar"] header, section[data-testid="stSidebar"] [data-testid="stNavSectionHeader"] {{
  color: #9C94D6 !important; }}
section[data-testid="stSidebar"] .stButton > button {{ background: rgba(255,255,255,.06); color: #E9E6FF;
  border: 1px solid rgba(255,255,255,.16); }}
section[data-testid="stSidebar"] .stButton > button:hover {{ border-color: #B9A8FF; color: #FFFFFF; background: rgba(255,255,255,.1); }}

.dp-brand {{ display: flex; align-items: center; gap: .7rem; margin: .2rem 0 1rem 0; }}
.dp-brand .mark {{ width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center;
  background: conic-gradient(from 200deg, {EXTRACT}, {VALIDATE}, {TRANSFORM}, {QUALITY}, {LOAD}, {EXTRACT}); }}
.dp-brand .mark svg {{ width: 26px; height: 26px; }}
.dp-brand .name {{ font-family: Sora, Manrope, sans-serif; font-weight: 700; font-size: 1.12rem; color: #FFFFFF; line-height: 1.1; }}
.dp-brand .tag {{ font-size: .74rem; color: #A9A2DD; }}
.dp-user {{ display: flex; align-items: center; gap: .65rem; padding: .7rem .75rem; border-radius: 14px;
  background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.1); margin: .2rem 0 .8rem 0; }}
.dp-avatar {{ width: 36px; height: 36px; border-radius: 50%; display: grid; place-items: center; font-weight: 800;
  color: #FFFFFF; background: var(--c); box-shadow: 0 0 0 3px {tint('#FFFFFF', .12)}; }}
.dp-user .u {{ color: #FFFFFF; font-weight: 700; font-size: .92rem; }}
.dp-user .r {{ font-size: .74rem; color: var(--c); font-weight: 700; }}
.dp-sys {{ margin: 0 0 .9rem 0; }}
.dp-sys div {{ display: flex; align-items: center; gap: .5rem; font-size: .8rem; color: #CFC9F5; padding: .18rem 0; }}
.dp-sys i {{ width: 8px; height: 8px; border-radius: 50%; background: var(--c); box-shadow: 0 0 0 3px {tint('#FFFFFF', .08)}; flex: none; }}
.dp-sys b {{ color: #FFFFFF; font-weight: 600; margin-left: auto; text-align: right; }}

/* ---------- buttons & widgets ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{ font-weight: 600; }}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"],
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
  background: linear-gradient(100deg, {VALIDATE}, {TRANSFORM}); border: none; color: #FFFFFF;
  box-shadow: 0 6px 18px -8px {tint(TRANSFORM, .8)}; }}
[data-testid="stBaseButton-primary"] p, [data-testid="stBaseButton-primaryFormSubmit"] p {{ color: #FFFFFF; }}
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {{
  filter: brightness(1.06); color: #FFFFFF; }}
.stDownloadButton > button {{ border-color: {tint(LOAD, .5)}; color: #05603A; background: {tint(LOAD, .08)}; }}
:focus-visible {{ outline: 2px solid {ACCENT} !important; outline-offset: 2px; }}
.stMain [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"],
.stMain [data-testid="stForm"] {{ background: {CARD}; border-radius: 16px; box-shadow: 0 10px 30px -22px {tint(NIGHT, .45)}; }}
[data-testid="stDataFrame"] {{ border-radius: 12px; overflow: hidden; }}
[data-testid="stExpander"] details {{ border-radius: 12px; background: {CARD}; }}
.stTabs [role="tablist"] {{ gap: .3rem; border-bottom: none; background: #E9EBF8; padding: .3rem;
  border-radius: 12px; width: fit-content; max-width: 100%; overflow-x: auto; }}
.stTabs [data-testid="stTab"] {{ padding: .4rem .95rem; border-radius: 9px; height: auto; }}
.stTabs [data-testid="stTab"] p {{ font-weight: 600; color: {MUTED}; }}
.stTabs [data-testid="stTab"][aria-selected="true"] {{ background: {CARD}; box-shadow: 0 2px 8px -4px {tint(NIGHT, .35)}; }}
.stTabs [data-testid="stTab"][aria-selected="true"] p {{ color: {ACCENT}; }}
.stTabs .react-aria-SelectionIndicator {{ display: none; }}

/* ---------- hero (signature) ---------- */
.dp-hero {{ position: relative; overflow: hidden; border-radius: 22px; padding: 1.5rem 1.7rem 1.35rem 1.7rem;
  margin: 0 0 1.3rem 0; color: #FFFFFF;
  background: linear-gradient(115deg, {NIGHT} 0%, var(--mid) 58%, var(--hi) 125%); }}
.dp-hero h1 {{ color: #FFFFFF; margin: 0; padding: 0; font-size: 2rem; font-weight: 700; position: relative; z-index: 1; }}
.dp-hero p {{ color: rgba(255,255,255,.82); margin: .4rem 0 0 0; max-width: 54ch; font-size: .96rem; position: relative; z-index: 1; }}
.dp-hero .pulse {{ position: absolute; right: -10px; top: 0; height: 100%; width: 44%; opacity: .9; pointer-events: none; }}
.dp-hero .pulse path {{ fill: none; stroke: rgba(255,255,255,.85); stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round;
  stroke-dasharray: 1400; stroke-dashoffset: 1400; animation: dp-draw 1.8s cubic-bezier(.6,.1,.2,1) .15s forwards; }}
.dp-hero .pulse path.glow {{ stroke: var(--hi); stroke-width: 9; opacity: .35; filter: blur(4px); }}
.dp-hero .orb {{ position: absolute; border-radius: 50%; filter: blur(2px); opacity: .5; pointer-events: none; }}
@keyframes dp-draw {{ to {{ stroke-dashoffset: 0; }} }}
.dp-chips {{ display: flex; flex-wrap: wrap; gap: .5rem; margin-top: 1rem; position: relative; z-index: 1; }}
.dp-chip {{ display: inline-flex; align-items: center; gap: .45rem; padding: .3rem .75rem .3rem .55rem; border-radius: 999px;
  background: rgba(255,255,255,.13); border: 1px solid rgba(255,255,255,.22); font-size: .82rem; color: #FFFFFF;
  backdrop-filter: blur(4px); }}
.dp-chip i {{ width: 8px; height: 8px; border-radius: 50%; background: var(--c, #FFFFFF); }}
.dp-chip b {{ font-weight: 800; }}

/* ---------- KPI tiles ---------- */
.dp-tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(148px, 1fr)); gap: .8rem; margin: .1rem 0 1.3rem 0; }}
.dp-tile {{ position: relative; border-radius: 16px; padding: .95rem 1rem .9rem 1rem; overflow: hidden;
  background: linear-gradient(160deg, {CARD} 30%, {tint('#FFFFFF', 0)} 100%), {CARD};
  border: 1px solid {LINE}; }}
.dp-tile::before {{ content: ""; position: absolute; inset: 0 0 auto 0; height: 4px; background: var(--c); }}
.dp-tile::after {{ content: ""; position: absolute; width: 120px; height: 120px; right: -40px; bottom: -60px; border-radius: 50%;
  background: var(--t); }}
.dp-tile .ic {{ width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center; font-size: .95rem;
  background: var(--t); color: var(--c); margin-bottom: .55rem; }}
.dp-tile .v {{ font-family: Sora, Manrope, sans-serif; font-size: 1.75rem; font-weight: 700; color: {INK}; line-height: 1.05; position: relative; z-index: 1; }}
.dp-tile .l {{ font-size: .84rem; color: {INK}; font-weight: 600; margin-top: .3rem; position: relative; z-index: 1; }}
.dp-tile .s {{ font-size: .76rem; color: {MUTED}; margin-top: .12rem; position: relative; z-index: 1; }}
.dp-tile .bar {{ height: 6px; border-radius: 99px; background: #EEF0F8; margin-top: .55rem; overflow: hidden; position: relative; z-index: 1; }}
.dp-tile .bar span {{ display: block; height: 100%; border-radius: 99px; background: var(--c); }}

/* ---------- section heading ---------- */
.dp-sec {{ display: flex; align-items: baseline; gap: .6rem; margin: 1.4rem 0 .6rem 0; }}
.dp-sec .dot {{ width: 10px; height: 10px; border-radius: 3px; background: var(--c); transform: translateY(-1px); flex: none; }}
.dp-sec h3 {{ margin: 0; padding: 0; font-size: 1.18rem !important; font-weight: 700; }}
.dp-sec span.c {{ color: {MUTED}; font-size: .85rem; }}

/* ---------- badges ---------- */
.dp-badge {{ display: inline-block; padding: .1rem .55rem; border-radius: 999px; font-size: .76rem; font-weight: 700;
  line-height: 1.5; white-space: nowrap; color: var(--c); background: var(--t); }}

/* ---------- stage track ---------- */
.dp-track {{ display: flex; align-items: flex-start; margin: .6rem 0 1.2rem 0; }}
.dp-stage {{ flex: 1; position: relative; text-align: center; min-width: 70px; }}
.dp-stage:not(:last-child)::after {{ content: ""; position: absolute; top: 15px; left: calc(50% + 17px);
  right: calc(-50% + 17px); height: 3px; border-radius: 3px; background: var(--edge, {LINE}); }}
.dp-node {{ width: 32px; height: 32px; border-radius: 50%; margin: 0 auto; display: flex; align-items: center;
  justify-content: center; font-size: .85rem; font-weight: 800; color: #FFFFFF; background: var(--c); border: 2px solid var(--c);
  box-shadow: 0 0 0 4px var(--halo, transparent); }}
.dp-node.hollow {{ background: #FFFFFF; color: var(--c); border-style: dashed; box-shadow: none; }}
.dp-stage .n {{ font-size: .82rem; font-weight: 700; margin-top: .4rem; color: var(--sc, {INK}); }}
.dp-stage .m {{ font-size: .74rem; color: {MUTED}; }}
.dp-track.compact .dp-node {{ width: 16px; height: 16px; font-size: 0; border-width: 2px; box-shadow: none; }}
.dp-track.compact .dp-stage:not(:last-child)::after {{ top: 6px; left: calc(50% + 9px); right: calc(-50% + 9px); }}
.dp-track.compact .dp-stage .n {{ font-size: .7rem; font-weight: 600; margin-top: .2rem; }}
.dp-track.compact {{ margin: .2rem 0 .2rem 0; }}

/* ---------- stage flow (overview) ---------- */
.dp-flow {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 0; margin: .2rem 0 1.2rem 0; }}
.dp-flow > div {{ position: relative; padding: .95rem 1.1rem .95rem 1.4rem; background: var(--t); color: {INK};
  clip-path: polygon(0 0, calc(100% - 16px) 0, 100% 50%, calc(100% - 16px) 100%, 0 100%, 16px 50%); margin-right: -10px; }}
.dp-flow > div:first-child {{ clip-path: polygon(0 0, calc(100% - 16px) 0, 100% 50%, calc(100% - 16px) 100%, 0 100%);
  border-radius: 14px 0 0 14px; padding-left: 1.1rem; }}
.dp-flow > div:last-child {{ clip-path: polygon(0 0, 100% 0, 100% 100%, 0 100%, 16px 50%); border-radius: 0 14px 14px 0; margin-right: 0; }}
.dp-flow .h {{ font-family: Sora, Manrope, sans-serif; font-weight: 700; color: var(--c); font-size: .98rem; }}
.dp-flow .d {{ font-size: .76rem; color: {MUTED}; margin: .15rem 0 .45rem 0; min-height: 2.1em; }}
.dp-flow .k {{ font-size: .8rem; }}
.dp-flow .k b {{ font-size: 1.05rem; }}

/* ---------- panels, lists ---------- */
.dp-panel {{ border-radius: 14px; padding: .75rem 1rem .8rem 1rem; margin: .4rem 0 .9rem 0;
  background: var(--t); border-left: 4px solid var(--c, {ACCENT}); }}
.dp-panel .t {{ font-size: .8rem; color: var(--c); font-weight: 800; margin-bottom: .2rem; }}
.dp-panel .b {{ color: {INK}; font-size: .93rem; }}
.dp-facts {{ margin: .2rem 0 1rem 0; padding: 0; list-style: none; }}
.dp-facts li {{ padding: .45rem 0 .45rem 1.3rem; border-bottom: 1px dashed {LINE}; font-size: .92rem; position: relative; }}
.dp-facts li::before {{ content: ""; position: absolute; left: .2rem; top: .9rem; width: 7px; height: 7px; border-radius: 50%;
  background: {LOAD}; }}
.dp-empty {{ border: 2px dashed {tint(VALIDATE, .35)}; background: {tint(VALIDATE, .04)}; border-radius: 16px;
  padding: 1.5rem 1.4rem; color: {MUTED}; }}
.dp-empty b {{ color: {INK}; font-size: 1rem; }}
.dp-check {{ display: flex; gap: .6rem; padding: .4rem .2rem; border-bottom: 1px solid {LINE}; font-size: .9rem; align-items: baseline; }}
.dp-check .i {{ width: 1.35rem; height: 1.35rem; flex: none; border-radius: 50%; display: grid; place-items: center;
  font-weight: 800; font-size: .75rem; color: #FFFFFF; transform: translateY(3px); }}
.dp-kv {{ display: grid; grid-template-columns: max-content 1fr; gap: .3rem 1.2rem; font-size: .9rem; margin: .3rem 0 1rem 0; }}
.dp-kv .k {{ color: {MUTED}; }}
.dp-kv > div:nth-child(even) {{ font-weight: 600; }}
.dp-synthetic {{ font-size: .76rem; color: {MUTED}; }}

/* feed rows (runs, incidents) */
.dp-row {{ display: grid; grid-template-columns: 6px 1fr; gap: .8rem; padding: .7rem .2rem; border-bottom: 1px solid {LINE}; }}
.dp-row:last-child {{ border-bottom: none; }}
.dp-row .rail {{ border-radius: 6px; background: var(--c); }}
.dp-row .t {{ font-weight: 700; font-size: .92rem; }}
.dp-row .m {{ color: {MUTED}; font-size: .8rem; margin-top: .1rem; }}

/* sample / report cards */
.dp-card {{ border-radius: 16px; padding: 1rem 1.1rem; background: {CARD}; border: 1px solid {LINE}; height: 100%;
  border-top: 5px solid var(--c); }}
.dp-card.flat {{ border: none; border-left: 4px solid var(--c); border-radius: 0; padding: .1rem 0 .1rem .8rem; background: transparent; height: auto; margin-bottom: .4rem; }}
.dp-card .h {{ display: flex; align-items: center; gap: .6rem; }}
.dp-card .ic {{ width: 34px; height: 34px; border-radius: 10px; background: var(--t); color: var(--c); display: grid;
  place-items: center; font-size: 1.05rem; flex: none; }}
.dp-card .ti {{ font-weight: 800; font-size: .95rem; word-break: break-word; }}
.dp-card .de {{ color: {MUTED}; font-size: .84rem; margin: .5rem 0 .2rem 0; min-height: 3.9em; }}

/* stepper (ingestion) */
.dp-steps {{ display: flex; gap: .6rem; margin: 0 0 1.1rem 0; flex-wrap: wrap; }}
.dp-step {{ flex: 1; min-width: 180px; display: flex; gap: .7rem; align-items: center; padding: .65rem .9rem;
  border-radius: 14px; background: {CARD}; border: 1px solid {LINE}; }}
.dp-step .no {{ width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center; font-weight: 800;
  background: #ECEEFA; color: {MUTED}; flex: none; }}
.dp-step .tx b {{ display: block; font-size: .9rem; }}
.dp-step .tx span {{ font-size: .76rem; color: {MUTED}; }}
.dp-step.done .no {{ background: {LOAD}; color: #FFFFFF; }}
.dp-step.now {{ border-color: var(--c); background: {tint(VALIDATE, .06)}; }}
.dp-step.now .no {{ background: var(--c); color: #FFFFFF; }}

@media (max-width: 900px) {{
  .dp-flow {{ grid-template-columns: 1fr; gap: .4rem; }}
  .dp-flow > div, .dp-flow > div:first-child, .dp-flow > div:last-child {{ clip-path: none; border-radius: 12px; margin: 0; padding-left: 1.1rem; }}
  .dp-hero .pulse {{ width: 100%; opacity: .35; }}
}}
@media (prefers-reduced-motion: reduce) {{
  * {{ transition: none !important; animation: none !important; }}
  .dp-hero .pulse path {{ stroke-dashoffset: 0; }}
}}
</style>
"""


def apply_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    register_plotly()


def register_plotly() -> None:
    if "datapulse" in pio.templates:
        pio.templates.default = "datapulse"
        return
    template = go.layout.Template()
    template.layout = go.Layout(
        font=dict(family="Manrope, Segoe UI, Arial, sans-serif", color=INK, size=12),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        colorway=SPECTRUM + [WARN, BAD],
        xaxis=dict(showgrid=False, linecolor=LINE, tickcolor=LINE, zeroline=False),
        yaxis=dict(gridcolor="#ECEEF7", zeroline=False, linecolor="rgba(0,0,0,0)"),
        margin=dict(l=8, r=8, t=40, b=8),
        title=dict(font=dict(size=15, color=INK, family="Sora, Manrope, sans-serif"), x=0, xanchor="left"),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, title_text=""),
        hoverlabel=dict(bgcolor=NIGHT, bordercolor=NIGHT, font=dict(color="#FFFFFF")),
    )
    pio.templates["datapulse"] = template
    pio.templates.default = "datapulse"
