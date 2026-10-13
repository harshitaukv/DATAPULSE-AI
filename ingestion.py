import pandas as pd
import streamlit as st

from components.runview import render_run
from components.session import call, can, client
from components.theme import BAD, CYAN, EXTRACT, LOAD, MUTED, QUALITY, STATUS_COLORS, TRANSFORM, VALIDATE
from components.ui import card, empty_state, fmt_int, html_line, ledger, page_header, section, short, steps

page_header("Data ingestion", "Upload a CSV or JSON dataset, check it against the pipeline contract, then run "
            "Extract, Validate, Transform, Quality and Load.", tone="extract",
            chips=[("CSV · JSON", "accepted formats", "#FFFFFF"), ("encrypted", "at rest", LOAD),
                   ("never executed", "files are parsed as data", QUALITY)])
c = client()
stepper = st.empty()


def show_steps() -> None:
    current = 0 if not st.session_state.get("dataset") else (1 if not st.session_state.get("last_run") else 3)
    with stepper.container():
        steps([("Choose data", "upload a file or pick a sample"), ("Check the contract", "columns, types, renames"),
               ("Run the pipeline", "five stages, with retries")], current, VALIDATE)


SAMPLE_STYLE = [("clean.json", QUALITY, "🧾"), ("clean", LOAD, "✨"), ("missing_duplicates", VALIDATE, "🔁"),
                ("schema", TRANSFORM, "📐"), ("low_volume", EXTRACT, "📉"), ("truncated", BAD, "✂️"),
                ("corrected", CYAN, "🩹")]


def sample_style(name: str) -> tuple[str, str]:
    return next(((col, ic) for key, col, ic in SAMPLE_STYLE if key in name), (VALIDATE, "📄"))
pipelines = call(c.get, "/api/v1/pipelines") or []
if not pipelines:
    st.stop()

if not can("upload"):
    st.info("Your role can view data but cannot upload or run pipelines. Ask an administrator for engineer access.")

upload_tab, sample_tab, existing_tab = st.tabs(["Upload a file", "Synthetic samples", "Previously uploaded"])

with upload_tab:
    file = st.file_uploader("CSV or JSON file", type=["csv", "json"], disabled=not can("upload"),
                            help="Files are validated, encrypted at rest and never executed.")
    if file is not None and st.button("Upload and validate", type="primary", disabled=not can("upload")):
        with st.spinner("Uploading and validating…"):
            result = call(c.upload, file.name, file.getvalue())
        if result:
            st.session_state["dataset"] = result["dataset"]
            st.session_state["preview"] = result["preview"]
            st.session_state.pop("last_run", None)

with sample_tab:
    st.markdown(f"<span style='color:{MUTED}'>These datasets are synthetic: identifiers and amounts are "
                "randomly generated from fixed seeds. Each one demonstrates a different failure mode.</span>",
                unsafe_allow_html=True)
    samples = call(c.get, "/api/v1/samples") or []
    grid = st.columns(3)
    for n, s in enumerate(samples):
        color, icon = sample_style(s["filename"])
        with grid[n % 3], st.container(border=True):
            card(s["filename"], s["description"], color, icon, flat=True)
            cols = st.columns(2)
            if cols[0].button("Use", key=f"use_{s['filename']}", disabled=not can("upload"), width="stretch"):
                with st.spinner("Generating and registering…"):
                    result = call(c.post, f"/api/v1/samples/{s['filename']}/import")
                if result:
                    st.session_state["dataset"] = result["dataset"]
                    st.session_state["preview"] = result["preview"]
                    st.session_state.pop("last_run", None)
            if cols[1].button("Download", key=f"dl_{s['filename']}", width="stretch"):
                st.session_state[f"sample_{s['filename']}"] = call(c.download, f"/api/v1/samples/{s['filename']}")
            if st.session_state.get(f"sample_{s['filename']}"):
                st.download_button(f"Save {s['filename']}", st.session_state[f"sample_{s['filename']}"], s["filename"],
                                   key=f"save_{s['filename']}")

with existing_tab:
    datasets = (call(c.get, "/api/v1/uploads", limit=100) or {}).get("items", [])
    if not datasets:
        empty_state("No datasets uploaded yet", "Upload a file or use a synthetic sample.")
    else:
        labels = {d["id"]: f"{d['original_filename']} · {fmt_int(d['row_count'])} rows · {d['uploaded_at'][:16].replace('T', ' ')}"
                  for d in datasets}
        chosen = st.selectbox("Dataset", list(labels), format_func=labels.get)
        if st.button("Select dataset"):
            st.session_state["dataset"] = next(d for d in datasets if d["id"] == chosen)
            st.session_state["preview"] = call(c.get, f"/api/v1/uploads/{chosen}/preview")
            st.session_state.pop("last_run", None)

dataset = st.session_state.get("dataset")
preview = st.session_state.get("preview")
show_steps()
if not dataset or not preview:
    st.stop()

section(dataset["original_filename"], "selected dataset", VALIDATE)
html_line(f"<span style='color:{MUTED};font-size:.88rem'>{fmt_int(dataset['row_count'])} rows · "
          f"{len(dataset['columns'])} columns · {dataset['size_bytes'] / 1024:,.1f} KB · SHA-256 {dataset['sha256'][:12]}…"
          f"{' · synthetic data' if dataset['is_synthetic'] else ''}</span>")

schema = preview["schema_check"]
ledger([dict(v=fmt_int(dataset["row_count"]), l="Rows", c=EXTRACT, icon="📄"),
        dict(v=fmt_int(len(dataset["columns"])), l="Columns", c=VALIDATE, icon="🧱"),
        dict(v=f"{dataset['size_bytes'] / 1024:,.1f} KB", l="File size", c=TRANSFORM, icon="💾"),
        dict(v=fmt_int(len(schema["missing_required"])), l="Missing required columns",
             c=BAD if schema["missing_required"] else LOAD, icon="⚠️" if schema["missing_required"] else "✅")])
cols = st.columns(3)
cols[0].markdown("**Contract check**")
if schema["missing_required"]:
    cols[0].error("Missing required: " + ", ".join(schema["missing_required"]))
elif schema["unexpected_columns"]:
    cols[0].warning("Extra columns: " + ", ".join(schema["unexpected_columns"]))
else:
    cols[0].success("All declared columns present")
if schema["suggested_mappings"]:
    cols[1].markdown("**Possible renames**")
    for src, info in schema["suggested_mappings"].items():
        cols[1].markdown(f"`{src}` → `{info['maps_to']}` (similarity {info['similarity']})")
if preview.get("header_normalisation"):
    cols[2].markdown("**Headers normalised**")
    cols[2].caption(", ".join(f"{k} → {v}" for k, v in preview["header_normalisation"].items()))

st.dataframe(pd.DataFrame(preview["rows"]), hide_index=True, width="stretch", height=260)
if preview.get("masked_columns"):
    st.caption(f"Sensitive columns are masked in previews: {', '.join(preview['masked_columns'])}.")

pipeline_labels = {p["id"]: p["name"] for p in pipelines}
pcol, scol = st.columns([1, 1])
pipeline_id = pcol.selectbox("Pipeline", list(pipeline_labels), format_func=pipeline_labels.get)
fault = None
if can("fault_injection"):
    with scol.expander("Failure simulation (testing)"):
        st.caption("Injects labelled, simulated failures so you can watch retries and escalation work.")
        enabled = st.checkbox("Simulate a transient database failure")
        stage = st.selectbox("Stage", ["load", "transform", "extract"], disabled=not enabled)
        times = st.number_input("Consecutive failures", 1, 5, 1, disabled=not enabled,
                                help="The retry limit is 2: one or two failures recover, three are escalated.")
        if enabled:
            fault = {"stage": stage, "fail_times": int(times), "kind": "transient_db"}

if st.button("Run pipeline", type="primary", disabled=not can("run_pipeline")):
    body = {"dataset_id": dataset["id"]}
    if fault:
        body["fault_injection"] = fault
    with st.spinner("Running Extract → Validate → Transform → Quality → Load…"):
        st.session_state["last_run"] = call(c.post, f"/api/v1/pipelines/{pipeline_id}/runs", body)

if run := st.session_state.get("last_run"):
    show_steps()
    section("Result", "", STATUS_COLORS.get(run["status"], VALIDATE))
    with st.container(border=True):
        render_run(run, key=f"ing_{short(run['id'])}")
