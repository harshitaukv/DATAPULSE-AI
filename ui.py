"""Reusable presentation helpers."""
from __future__ import annotations

import html
from datetime import datetime

import streamlit as st

from components.theme import (ACCENT, BAD, INCIDENT_STATUS_COLORS, LINE, MUTED, NEUTRAL, OK, RESULT_COLORS,
                              SEVERITY_COLORS, SPECTRUM, STAGE_COLORS, STATUS_COLORS, TONES, WARN, tint)

STAGES = ["extract", "validate", "transform", "quality", "load"]

_PULSE = ("M0,92 L110,92 L128,92 L142,66 L156,116 L174,24 L194,134 L210,80 L226,92 L320,92 L336,76 L350,104 "
          "L362,92 L450,92 L466,44 L482,118 L498,92 L560,92 L574,84 L586,98 L600,92")


def esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def page_header(title: str, subtitle: str = "", tone: str = "validate",
                chips: list[tuple[str, str, str | None]] | None = None) -> None:
    """Gradient hero with the pulse mark. chips: (value, label, colour)."""
    mid, hi = TONES.get(tone, TONES["validate"])
    chip_html = ""
    if chips:
        chip_html = '<div class="dp-chips">' + "".join(
            f'<span class="dp-chip" style="--c:{c or "#FFFFFF"}"><i></i><b>{esc(v)}</b> {esc(l)}</span>'
            for v, l, c in chips) + "</div>"
    svg = (f'<svg class="pulse" viewBox="0 0 600 160" preserveAspectRatio="none" aria-hidden="true">'
           f'<path class="glow" d="{_PULSE}" vector-effect="non-scaling-stroke"/>'
           f'<path d="{_PULSE}" vector-effect="non-scaling-stroke"/></svg>')
    orbs = (f'<span class="orb" style="width:220px;height:220px;right:18%;top:-120px;background:{tint(hi, .45)}"></span>'
            f'<span class="orb" style="width:140px;height:140px;right:-40px;bottom:-70px;background:{tint("#FFFFFF", .18)}"></span>')
    st.markdown(f'<div class="dp-hero" style="--mid:{mid};--hi:{hi}">{orbs}{svg}<h1>{esc(title)}</h1>'
                + (f"<p>{esc(subtitle)}</p>" if subtitle else "") + chip_html + "</div>", unsafe_allow_html=True)


def ledger(items: list) -> None:
    """KPI tiles. Each item is a dict {v, l, s, c, icon, pct} or a tuple (value, label, sublabel[, colour])."""
    cells = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            it = {"v": it[0], "l": it[1], "s": it[2], "c": it[3] if len(it) > 3 else None}
        c = it.get("c") or SPECTRUM[i % len(SPECTRUM)]
        icon = f'<div class="ic">{esc(it["icon"])}</div>' if it.get("icon") else ""
        pct = it.get("pct")
        bar = (f'<div class="bar"><span style="width:{max(0, min(100, pct)):.1f}%"></span></div>'
               if pct is not None else "")
        cells.append(f'<div class="dp-tile" style="--c:{c};--t:{tint(c, .12)}">{icon}<div class="v">{esc(it["v"])}</div>'
                     f'<div class="l">{esc(it["l"])}</div>'
                     + (f'<div class="s">{esc(it["s"])}</div>' if it.get("s") else "") + bar + "</div>")
    st.markdown(f'<div class="dp-tiles">{"".join(cells)}</div>', unsafe_allow_html=True)


def section(title: str, caption: str = "", color: str = ACCENT) -> None:
    st.markdown(f'<div class="dp-sec" style="--c:{color}"><span class="dot"></span><h3>{esc(title)}</h3>'
                + (f'<span class="c">{esc(caption)}</span>' if caption else "") + "</div>", unsafe_allow_html=True)


def badge(text: str, color: str) -> str:
    return f'<span class="dp-badge" style="--c:{color};--t:{tint(color, .14)}">{esc(text)}</span>'


def status_badge(status: str) -> str:
    return badge(status.replace("_", " "), STATUS_COLORS.get(status, NEUTRAL))


def severity_badge(sev: str) -> str:
    return badge(sev, SEVERITY_COLORS.get(sev, NEUTRAL))


def incident_status_badge(status: str) -> str:
    return badge(status.replace("_", " "), INCIDENT_STATUS_COLORS.get(status, NEUTRAL))


def result_badge(result: str) -> str:
    return badge(result.replace("_", " "), RESULT_COLORS.get(result, NEUTRAL))


def stage_track(stage_log: list[dict], compact: bool = False) -> None:
    st.markdown(stage_track_html(stage_log, compact), unsafe_allow_html=True)


def stage_track_html(stage_log: list[dict], compact: bool = False) -> str:
    by_name = {s["name"]: s for s in stage_log or []}
    parts = []
    for i, name in enumerate(STAGES):
        s = by_name.get(name, {"status": "pending", "attempts": []})
        attempts = len(s.get("attempts", []))
        status = s["status"]
        if status == "succeeded" and attempts > 1:
            color, symbol, meta = WARN, "↻", f"{attempts} attempts"
        elif status == "succeeded":
            color, symbol, meta = OK, "✓", f"{s.get('duration_seconds', 0):.2f}s"
        elif status == "failed":
            color, symbol, meta = BAD, "✕", f"failed after {attempts}" if attempts > 1 else "failed"
        else:
            color, symbol, meta = NEUTRAL, "", status
        nxt = by_name.get(STAGES[i + 1], {}).get("status") if i + 1 < len(STAGES) else None
        edge = (f"linear-gradient(90deg,{STAGE_COLORS[name]},{STAGE_COLORS[STAGES[i + 1]]})"
                if status == "succeeded" and nxt in ("succeeded", "failed", "running") else LINE)
        hollow = " hollow" if status in ("skipped", "pending") else ""
        parts.append(f'<div class="dp-stage" style="--c:{color};--edge:{edge};--halo:{tint(color, .18)};'
                     f'--sc:{STAGE_COLORS[name]}"><div class="dp-node{hollow}">'
                     f'{symbol}</div><div class="n">{name.title()}</div>'
                     + ("" if compact else f'<div class="m">{esc(meta)}</div>') + "</div>")
    return f'<div class="dp-track{" compact" if compact else ""}" role="img" aria-label="Pipeline stages">' \
           + "".join(parts) + "</div>"


def stage_flow(stats: dict[str, tuple[str, str]]) -> None:
    """The five ETL stages as a chevron strip. stats: stage -> (description, html metric line)."""
    cells = "".join(f'<div style="--c:{STAGE_COLORS[s]};--t:{tint(STAGE_COLORS[s], .13)}"><div class="h">{s.title()}</div>'
                    f'<div class="d">{esc(stats[s][0])}</div><div class="k">{stats[s][1]}</div></div>' for s in STAGES)
    st.markdown(f'<div class="dp-flow">{cells}</div>', unsafe_allow_html=True)


def panel(title: str, body: str, color: str = ACCENT) -> None:
    st.markdown(f'<div class="dp-panel" style="--c:{color};--t:{tint(color, .08)}"><div class="t">{esc(title)}</div>'
                f'<div class="b">{esc(body)}</div></div>', unsafe_allow_html=True)


def feed_row(title_html: str, meta_html: str, color: str, right_html: str = "") -> str:
    right = f'<div style="text-align:right;font-size:.82rem">{right_html}</div>' if right_html else ""
    grid = "grid-template-columns:6px 1fr auto" if right else ""
    return (f'<div class="dp-row" style="--c:{color};{grid}"><div class="rail"></div>'
            f'<div><div class="t">{title_html}</div><div class="m">{meta_html}</div></div>{right}</div>')


def card(title: str, body: str, color: str, icon: str = "", flat: bool = False) -> None:
    st.markdown(f'<div class="dp-card{" flat" if flat else ""}" style="--c:{color};--t:{tint(color, .12)}"><div class="h">'
                + (f'<div class="ic">{esc(icon)}</div>' if icon else "")
                + f'<div class="ti">{esc(title).replace("_", "_<wbr>")}</div></div><div class="de">{esc(body)}</div></div>',
                unsafe_allow_html=True)


def steps(items: list[tuple[str, str]], current: int, color: str = ACCENT) -> None:
    """A real sequence: items are (title, hint); steps before `current` are done."""
    out = []
    for i, (t, h) in enumerate(items):
        state = "done" if i < current else ("now" if i == current else "")
        out.append(f'<div class="dp-step {state}" style="--c:{color}"><div class="no">{"✓" if i < current else i + 1}</div>'
                   f'<div class="tx"><b>{esc(t)}</b><span>{esc(h)}</span></div></div>')
    st.markdown(f'<div class="dp-steps">{"".join(out)}</div>', unsafe_allow_html=True)


def facts(items: list[str]) -> None:
    if items:
        st.markdown('<ul class="dp-facts">' + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>",
                    unsafe_allow_html=True)


def kv(pairs: list[tuple[str, object]]) -> None:
    rows = "".join(f'<div class="k">{esc(k)}</div><div>{v if str(v).startswith("<span") else esc(v)}</div>'
                   for k, v in pairs if v is not None and v != "")
    st.markdown(f'<div class="dp-kv">{rows}</div>', unsafe_allow_html=True)


def checks(items: list[dict]) -> None:
    rows = []
    for c in items:
        ok = c.get("passed", True)
        detail = c.get("detail") if c.get("detail") not in (None, []) else c.get("value")
        if c.get("status") == "insufficient_history":
            icon, color, detail = "–", NEUTRAL, "insufficient history (not evaluated)"
        else:
            icon, color = ("✓", OK) if ok else ("✕", BAD)
        rows.append(f'<div class="dp-check"><span class="i" style="background:{color}">{icon}</span>'
                    f'<span>{esc(c["check"].replace("_", " ").capitalize())}'
                    + (f' <span style="color:{MUTED}">· {esc(detail)}</span>' if detail not in (None, "") else "")
                    + "</span></div>")
    st.markdown("".join(rows), unsafe_allow_html=True)


def empty_state(title: str, body: str) -> None:
    st.markdown(f'<div class="dp-empty"><b>{esc(title)}</b><br>{esc(body)}</div>', unsafe_allow_html=True)


def html_line(text: str) -> None:
    st.markdown(text, unsafe_allow_html=True)


def fmt_int(v) -> str:
    return "–" if v is None else f"{int(v):,}"


def fmt_num(v, digits: int = 1, suffix: str = "") -> str:
    return "–" if v is None else f"{v:,.{digits}f}{suffix}"


def fmt_time(value: str | None) -> str:
    if not value:
        return "–"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y, %H:%M")
    except ValueError:
        return str(value)


def short(id_: str | None) -> str:
    return id_[:8] if id_ else "–"


BRAND_HTML = ('<div class="dp-brand"><div class="mark"><svg viewBox="0 0 26 26" aria-hidden="true">'
              '<path d="M1 14h5l2.5-6 4 12 3-9 2 3h7.5" fill="none" stroke="#FFFFFF" stroke-width="2.4" '
              'stroke-linecap="round" stroke-linejoin="round"/></svg></div>'
              '<div><div class="name">DataPulse AI</div><div class="tag">Pipeline health, explained</div></div></div>')


def nav_link(page: str, label: str, icon: str) -> None:
    """Link to another dashboard page; skipped when the page runs outside the navigation (e.g. in tests)."""
    try:
        st.page_link(page, label=label, icon=icon)
    except Exception:  # StreamlitAPIException when the page is not registered with st.navigation
        pass
