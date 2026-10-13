"""Upload validation (required tests 1-4, 19)."""
import json

from app.ingestion import sample_data as sd
from tests.conftest import upload


def test_valid_csv_upload(client, engineer):
    r = upload(client, engineer, "sales.csv", sd.generate_clean(200, seed=1).to_csv(index=False).encode())
    assert r.status_code == 201
    body = r.json()
    assert body["dataset"]["row_count"] == 200
    assert body["preview"]["schema_check"]["conforms"] is True
    assert body["dataset"]["file_format"] == "csv"


def test_valid_json_upload(client, engineer):
    records = sd.generate_clean(50, seed=2).to_dict(orient="records")
    r = upload(client, engineer, "sales.json", json.dumps(records).encode(), "application/json")
    assert r.status_code == 201
    assert r.json()["dataset"]["row_count"] == 50
    wrapped = upload(client, engineer, "wrapped.json", json.dumps({"records": records}).encode(), "application/json")
    assert wrapped.status_code == 201


def test_unsupported_file_type_rejected(client, engineer):
    r = upload(client, engineer, "malware.exe", b"MZ\x90\x00binary", "application/octet-stream")
    assert r.status_code == 422
    assert "Unsupported file type" in r.json()["detail"]


def test_empty_dataset_rejected(client, engineer):
    assert upload(client, engineer, "empty.csv", b"").status_code == 422
    header_only = upload(client, engineer, "header.csv", b"transaction_id,customer_id\n")
    assert header_only.status_code == 422
    assert "no data rows" in header_only.json()["detail"]
    assert upload(client, engineer, "empty.json", b"[]", "application/json").status_code == 422


def test_malformed_and_binary_files_rejected(client, engineer):
    assert upload(client, engineer, "bad.json", b'[{"a": 1}, {"a": ', "application/json").status_code == 422
    assert upload(client, engineer, "bin.csv", b"a,b\n\x00\x01\x02,3\n").status_code == 422


def test_upload_size_limit(client, engineer):
    big = b"transaction_id,customer_id\n" + b"T1,C1\n" * 400_000  # ~2.4 MB > 2 MB test limit
    r = upload(client, engineer, "big.csv", big)
    assert r.status_code == 413
    assert "limit" in r.json()["detail"]


def test_filename_sanitised_and_path_not_exposed(client, engineer):
    r = upload(client, engineer, "../../etc/pass wd.csv", sd.generate_clean(10, seed=3).to_csv(index=False).encode())
    assert r.status_code == 201
    ds = r.json()["dataset"]
    assert ds["original_filename"] == "pass_wd.csv"
    assert "stored_filename" not in ds and "/" not in json.dumps(ds["original_filename"])


def test_uploads_are_encrypted_at_rest(client, engineer, db):
    from app.database.models import Dataset
    from app.services.storage import upload_path
    content = sd.generate_clean(30, seed=4).to_csv(index=False).encode()
    ds_id = upload(client, engineer, "secret.csv", content).json()["dataset"]["id"]
    stored = upload_path(db.get(Dataset, ds_id).stored_filename).read_bytes()
    assert b"transaction_id" not in stored and content not in stored
