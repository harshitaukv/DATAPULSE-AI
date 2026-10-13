# DataPulse AI - Evaluation Results

Generated 2026-10-12 09:20 UTC by `python scripts/evaluate.py` on 3.12.3, database SQLite (isolated temporary database), embeddings `tfidf`. All data is synthetic and generated from fixed seeds; rerun the script to reproduce.

## 1. Data-quality detection (100 labeled datasets, full pipeline, rule engine)

Issue severity was randomised, including mild cases below the configured thresholds (missing 5-40% of rows in four columns, duplicates 1-12%, volume kept 5-70%), so a detection rate below 100% is expected and reflects the thresholds, not a defect.

| Injected issue | Datasets | Detected | Detection rate |
|---|---:|---:|---:|
| missing | 25 | 25 | 100.0% |
| duplicates | 20 | 20 | 100.0% |
| schema | 15 | 15 | 100.0% |
| volume | 15 | 12 | 80.0% |

Overall detection rate on the 75 datasets with injected issues: **96.0%**. False alarms on the 25 clean datasets: **0** (0.0%).

Missed cases (injected issue not detected):

| Label | Injection | Status |
|---|---|---|
| volume | {"volume_kept_fraction": 0.558} | warning |
| volume | {"volume_kept_fraction": 0.517} | warning |
| volume | {"volume_kept_fraction": 0.531} | warning |

## 2. Isolation Forest anomaly detection

Trained on 40 clean synthetic runs; tested on 85 runs from experiment 1 (15 excluded: schema failures stop before features are computed). Positive class = any injected issue.

| Detector | Precision | Recall | F1 | False-positive rate | TP | FP | FN | TN |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Isolation Forest | 0.9412 | 0.2667 | 0.4156 | 0.04 | 16 | 1 | 44 | 24 |
| Rules only | 1.0 | 0.95 | 0.9744 | 0.0 | 57 | 0 | 3 | 25 |
| Rules OR Isolation Forest | 0.9836 | 1.0 | 0.9917 | 0.04 | 60 | 1 | 0 | 24 |

Contamination setting used: `0.02`. Ablation over the contamination parameter (same training and test data):

| Contamination | Precision | Recall | F1 | False-positive rate |
|---|---:|---:|---:|---:|
| auto | 0.7963 | 0.7167 | 0.7544 | 0.44 |
| 0.02 | 0.9412 | 0.2667 | 0.4156 | 0.04 |
| 0.05 | 0.8421 | 0.2667 | 0.4051 | 0.12 |
| 0.1 | 0.8421 | 0.5333 | 0.6531 | 0.24 |

Flags by label: clean: 1/25, missing: 1/25, duplicates: 0/20, volume: 15/15.

## 3. RAG retrieval relevance

24 labeled questions over 51 knowledge-base chunks (backend `tfidf`, model `tfidf-1-2gram`).

| Metric | Value |
|---|---:|
| Hit@1 | 87.5% |
| Hit@3 | 91.67% |
| MRR | 0.8958 |
| Off-topic questions correctly rejected | 5/5 |

Questions where the expected document was not in the top 3: "LLM request timed out"; "should a schema mismatch be retried".

## 4. Processing throughput

| Records | Runs | Median duration (s) | Records/second |
|---:|---:|---:|---:|
| 1,000 | 3 | 0.175 | 5,720 |
| 10,000 | 3 | 0.407 | 24,539 |
| 50,000 | 2 | 0.89 | 56,186 |
| 100,000 | 2 | 1.556 | 64,277 |

Duration covers the full run: decrypting the upload, parsing, validation, cleaning, quality rules, Isolation Forest scoring, encrypted output writing and database persistence.

## 5. Recovery

Failure simulation injected 1, 2 or 3 consecutive transient failures into the load stage (5 runs each); the retry limit is 2.

| Measure | Result |
|---|---:|
| Eligible transient failures auto-recovered and output-validated | 10/10 (100.0%) |
| Failures beyond the retry limit correctly stopped and escalated | 5/5 |
| Schema incidents recovered with an approved column mapping | 5/5 |

## 6. Incident explanations

Mode evaluated: `deterministic_fallback`. One incident per rule type (8 types).

| Check | Result |
|---|---:|
| Summary names the correct incident category | 8/8 |
| No unverified numbers (every number traceable to evidence) | 8/8 |
| Relevant troubleshooting document in top 3 | 5/5 |

| Rule | Expected document | Retrieved top 3 |
|---|---|---|
| DQ_DUPLICATES | 03_duplicate_records | 03_duplicate_records, 03_duplicate_records, 03_duplicate_records |
| DQ_MISSING_VALUES | 04_missing_values | 04_missing_values, 04_missing_values, 04_missing_values |
| ML_ANOMALY | - | 11_pipeline_monitoring, 11_pipeline_monitoring, 11_pipeline_monitoring |
| REPEATED_FAILURE | - | 07_database_connection_errors, 10_safe_retry_strategies, 04_missing_values |
| RUNTIME_TRANSIENT | 07_database_connection_errors | 07_database_connection_errors, 07_database_connection_errors, 07_database_connection_errors |
| SCHEMA_MISSING_COLUMNS | 01_missing_column_errors | 01_missing_column_errors, 01_missing_column_errors, 04_missing_values |
| VOLUME_DROP | 11_pipeline_monitoring | 09_data_quality_validation, 11_pipeline_monitoring, 11_pipeline_monitoring |
| VOLUME_SPIKE | - | 09_data_quality_validation, 11_pipeline_monitoring, 11_pipeline_monitoring |

LLM-generated explanations were not evaluated here because no LLM API key was configured in the evaluation environment. With LLM_API_KEY and LLM_MODEL set, the same script evaluates the LLM output (schema validity and grounding check) instead of the deterministic summaries.

## Limitations

- All datasets are synthetic; real production data has messier, correlated failure modes.
- The Isolation Forest is evaluated on run-level features from one synthetic pipeline; results do not transfer automatically to other pipelines.
- Throughput was measured on a single shared CPU in a container; absolute numbers depend on hardware.
- Pandas processing is single-node; it is not distributed big-data processing.
