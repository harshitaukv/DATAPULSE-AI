"""Run detail rendering shared by the ingestion and monitor pages."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from components.session import call, can, client
from components.theme import BAD, CYAN, EXTRACT, LOAD, MUTED, OK, QUALITY, WARN
from components.ui import (esc, fmt_int, fmt_num, fmt_time, html_line, kv, ledger, panel, severity_badge, short, stage_track,
                           status_badge)


def render_run(run: dict, show_incidents: bool = True, key: str = "run") -> None:
    html_line(f"<h3 style='margin-top:.2rem'>Run {short(run['id'])} {status_badge(run['status'])}</h3>"
              f"<span style='color:{MUTED};font-size:.84rem'>{esc(run.get('dataset_filename') or '')} · {fmt_time(run['started_at'])}</span>")
    stage_track(run.get("stage_log", []))
    ledger([dict(v=fmt_int(run["input_records"]), l="Input records", c=EXTRACT, icon="📥"),
            dict(v=fmt_int(run["output_records"]), l="Output records", c=LOAD, icon="📤"),
            dict(v=fmt_int(run["quarantined_records"]), l="Quarantined", c=WARN, icon="🧺"),
            dict(v=fmt_num(run["quality_score"]), l="Quality score", c=QUALITY, icon="⭐", pct=run["quality_score"]),
            dict(v=fmt_num(run["duration_seconds"], 2, " s"), l="Duration", c=CYAN, icon="⏱️")])
    left, right = st.columns([1.2, 1])
    with left:
        kv([("Dataset", run.get("dataset_filename")), ("Trigger", run["trigger_type"]),
            ("Started", fmt_time(run["started_at"])), ("Pipeline run id", run["id"]),
            ("Parent run", short(run["parent_run_id"]) if run.get("parent_run_id") else None),
            ("Failure simulation", json.dumps(run["run_options"]["fault_injection"])
             if run.get("run_options", {}).get("fault_injection") else None),
            ("Column mapping", json.dumps(run["run_options"]["column_mapping"])
             if run.get("run_options", {}).get("column_mapping") else None)])
    with right:
        if run["status"] == "failed":
            panel(f"Failed in {run['failed_stage']} ({run['error_type']})", run["error_message"] or "", BAD)
        elif run.get("summary"):
            panel("Summary", run["summary"], WARN if run["status"] == "warning" else OK)
        anomaly = run.get("anomaly") or {}
        if anomaly.get("status") == "evaluated":
            verdict = "unusual" if anomaly["is_anomaly"] else "normal"
            html_line(f"<span style='color:{MUTED};font-size:.86rem'>Isolation Forest: {verdict} "
                      f"(score {anomaly['decision_score']}, trained on {anomaly['history_size']} runs)</span>")
        elif anomaly.get("status") == "insufficient_history":
            html_line(f"<span style='color:{MUTED};font-size:.86rem'>Isolation Forest: not evaluated, "
                      f"{anomaly['history_size']} of {anomaly['required']} historical runs available</span>")

    downloads = st.columns(3)
    c = client()
    with downloads[0]:
        if st.button("Prepare quality report (JSON)", key=f"{key}_rep"):
            st.session_state[f"{key}_rep_bytes"] = call(c.download, f"/api/v1/runs/{run['id']}/download/report")
        if st.session_state.get(f"{key}_rep_bytes"):
            st.download_button("Download quality report", st.session_state[f"{key}_rep_bytes"],
                               f"quality_report_{short(run['id'])}.json", "application/json", key=f"{key}_repdl")
    for col, kind, flag in ((downloads[1], "processed", "has_processed_file"),
                            (downloads[2], "quarantine", "has_quarantine_file")):
        with col:
            if run.get(flag) and can("download_records"):
                if st.button(f"Prepare {kind} records (CSV)", key=f"{key}_{kind}"):
                    st.session_state[f"{key}_{kind}_bytes"] = call(c.download, f"/api/v1/runs/{run['id']}/download/{kind}")
                if st.session_state.get(f"{key}_{kind}_bytes"):
                    st.download_button(f"Download {kind} CSV", st.session_state[f"{key}_{kind}_bytes"],
                                       f"{kind}_{short(run['id'])}.csv", "text/csv", key=f"{key}_{kind}dl")

    with st.expander("Stage attempts"):
        rows = [{"stage": s["name"], "status": s["status"], "attempt": a["attempt"], "attempt status": a["status"],
                 "seconds": a["duration_seconds"], "error": a.get("error"), "retry delay (s)": a.get("retry_delay_seconds")}
                for s in run.get("stage_log", []) for a in s.get("attempts", [])]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    if show_incidents:
        incidents = (call(c.get, "/api/v1/incidents", run_id=run["id"]) or {}).get("items", [])
        if incidents:
            st.markdown("**Incidents opened by this run**")
            for inc in incidents:
                html_line(f"{severity_badge(inc['severity'])} {inc['title']} "
                          f"<span style='color:{MUTED};font-size:.82rem'>· {inc['rule_id']} · {inc['status'].replace('_', ' ')}</span>")
            st.caption("Investigate them on the Incidents and AI incident analyst pages.")
