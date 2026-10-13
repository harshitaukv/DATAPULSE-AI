"""ETL, data quality and monitoring (required tests 5-11)."""
from app.ingestion import sample_data as sd
from tests.conftest import incident, incidents_for, upload_and_run


def rules(client, headers, run_id):
    return {i["rule_id"] for i in incidents_for(client, headers, run_id)}


def test_missing_required_column_stops_run(client, engineer, baseline):
    df = sd.generate_clean(500, seed=21).drop(columns=["customer_id"])
    run = upload_and_run(client, engineer, "nocust.csv", sd.to_csv_bytes(df))
    assert run["status"] == "failed" and run["failed_stage"] == "validate"
    assert run["error_type"] == "schema_mismatch" and not run["has_processed_file"]
    inc = incident(client, engineer, run["id"], "SCHEMA_MISSING_COLUMNS")
    assert inc["severity"] == "critical"
    assert inc["evidence"]["missing_required"] == ["customer_id"]


def test_duplicates_detected_and_quarantined(client, engineer, baseline):
    df = sd.inject_missing_and_duplicates(sd.generate_clean(4800, seed=22), seed=5, missing_frac=0, dup_frac=0.08)
    run = upload_and_run(client, engineer, "dups.csv", sd.to_csv_bytes(df))
    assert "DQ_DUPLICATES" in rules(client, engineer, run["id"])
    assert run["metrics"]["duplicates_removed"] == run["metrics"]["duplicate_records"] > 0
    assert run["output_records"] + run["quarantined_records"] == run["input_records"]
    logs = client.get("/api/v1/recovery-logs", headers=engineer).json()["items"]
    assert any(l["action"] == "apply_deduplication" and l["result"] == "success" for l in logs)


def test_missing_values_detected(client, engineer, baseline):
    df = sd.inject_missing_and_duplicates(sd.generate_clean(5000, seed=23), seed=6, missing_frac=0.3, dup_frac=0)
    run = upload_and_run(client, engineer, "missing.csv", sd.to_csv_bytes(df))
    assert "DQ_MISSING_VALUES" in rules(client, engineer, run["id"])
    assert run["metrics"]["rows_with_missing_required"] > 0
    q = client.get(f"/api/v1/runs/{run['id']}/quality", headers=engineer).json()
    assert any(k.startswith("missing") for k in q["quarantine_summary"])


def test_invalid_numeric_values_quarantined(client, engineer, baseline):
    df = sd.generate_clean(5000, seed=24).astype(object)
    df.loc[:199, "unit_price"] = "N/A"
    df.loc[200:299, "quantity"] = -2
    run = upload_and_run(client, engineer, "invalid.csv", sd.to_csv_bytes(df))
    assert "DQ_INVALID_VALUES" in rules(client, engineer, run["id"])
    assert run["metrics"]["type_errors_by_column"]["unit_price"] == 200
    assert run["metrics"]["constraint_violations"]["quantity_below_min"] == 100
    assert run["output_records"] == 4700


def test_schema_drift_extra_columns(client, engineer, baseline):
    df = sd.generate_clean(5000, seed=25)
    df["loyalty_tier"] = "gold"
    run = upload_and_run(client, engineer, "drift.csv", sd.to_csv_bytes(df))
    assert run["status"] == "warning" and "SCHEMA_DRIFT" in rules(client, engineer, run["id"])
    assert run["output_records"] == 5000 and "loyalty_tier" not in run["report"]["schema"]["expected_columns"]


def test_abnormal_record_count_reduction(client, engineer, baseline):
    run = upload_and_run(client, engineer, "tiny.csv", sd.to_csv_bytes(sd.generate_clean(400, seed=26)))
    found = [i for i in incidents_for(client, engineer, run["id"]) if i["rule_id"] == "VOLUME_DROP"]
    assert found and found[0]["evidence"]["deviation_pct"] < -50
    assert run["status"] == "warning"  # anomaly, not failure: the data itself was valid


def test_normal_data_not_flagged(client, engineer, baseline):
    run = upload_and_run(client, engineer, "normal.csv", sd.to_csv_bytes(sd.generate_clean(5050, seed=27)))
    assert run["status"] == "succeeded"
    assert incidents_for(client, engineer, run["id"]) == []
    assert run["anomaly"]["status"] == "evaluated" and run["anomaly"]["is_anomaly"] is False
    assert run["quality_score"] == 100.0


def test_insufficient_history_not_flagged(client, admin):
    pipe = client.post("/api/v1/pipelines", headers=admin, json={
        "name": "fresh_pipeline", "config": {"columns": {"transaction_id": {"type": "string"}}}}).json()
    ds = client.post("/api/v1/uploads", headers=admin,
                     files={"file": ("f.csv", b"transaction_id\nA\nB\nC\n", "text/csv")}).json()["dataset"]
    run = client.post(f"/api/v1/pipelines/{pipe['id']}/runs", json={"dataset_id": ds["id"]}, headers=admin).json()
    assert run["status"] == "succeeded"
    assert run["anomaly"]["status"] == "insufficient_history"
    assert run["report"]["baseline"]["status"] == "insufficient_history"


def test_truncated_input_stops_run(client, engineer, baseline):
    run = upload_and_run(client, engineer, "cut.csv", sd.truncate_rows(sd.generate_clean(3000, seed=28)))
    assert run["status"] == "failed" and run["error_type"] == "incomplete_input"
    assert "INPUT_TRUNCATED" in rules(client, engineer, run["id"])


def test_json_and_csv_produce_same_output(client, engineer, baseline):
    import json
    df = sd.generate_clean(5000, seed=29)
    a = upload_and_run(client, engineer, "same.csv", sd.to_csv_bytes(df))
    ds = client.post("/api/v1/uploads", headers=engineer, files={
        "file": ("same.json", json.dumps(df.to_dict(orient="records")).encode(), "application/json")}).json()
    b = client.post("/api/v1/pipelines/1/runs", json={"dataset_id": ds["dataset"]["id"]}, headers=engineer).json()
    assert a["output_records"] == b["output_records"] and a["quality_score"] == b["quality_score"]
