"""Authentication, authorisation, auditing, persistence errors (required test 18) and reports."""
from sqlalchemy.exc import OperationalError

from app.ingestion import sample_data as sd
from tests.conftest import upload_and_run


def test_requires_authentication(client):
    assert client.get("/api/v1/runs").status_code == 401
    assert client.get("/api/v1/runs", headers={"Authorization": "Bearer forged.token.value"}).status_code == 401


def test_bad_login_and_throttling(client):
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"username": "viewer", "password": "nope"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"username": "viewer", "password": "Viewer-test-123"})
    assert r.status_code == 429  # locked out after repeated failures, even with the right password


def test_admin_only_endpoints(client, engineer, admin):
    assert client.get("/api/v1/audit-logs", headers=engineer).status_code == 403
    assert client.get("/api/v1/audit-logs", headers=admin).status_code == 200
    assert client.post("/api/v1/assistant/rebuild-index", headers=engineer).status_code == 403
    assert client.get("/api/v1/reports/audit_log", headers=engineer).status_code == 403


def test_audit_trail_records_actions(client, engineer, admin, baseline):
    upload_and_run(client, engineer, "audit.csv", sd.to_csv_bytes(sd.generate_clean(100, seed=81)))
    actions = {a["action"] for a in client.get("/api/v1/audit-logs", params={"limit": 500}, headers=admin).json()["items"]}
    assert {"login", "upload_dataset", "run_pipeline"} <= actions


def test_viewer_sees_masked_records(client, engineer, viewer, baseline):
    df = sd.inject_missing_and_duplicates(sd.generate_clean(5000, seed=82), seed=9, missing_frac=0.2, dup_frac=0)
    run = upload_and_run(client, engineer, "mask.csv", sd.to_csv_bytes(df))
    q = client.get(f"/api/v1/runs/{run['id']}/quality", headers=viewer).json()
    ids = [r["customer_id"] for r in q["quarantine_sample"] if r["customer_id"]]
    assert q["records_masked"] and ids and all("*" in i for i in ids)
    assert client.get(f"/api/v1/runs/{run['id']}/download/processed", headers=viewer).status_code == 403
    assert client.get(f"/api/v1/runs/{run['id']}/download/processed", headers=engineer).status_code == 200


def test_database_errors_return_safe_503(client, engineer, monkeypatch):
    from app.services import pipeline_service

    def broken(*a, **k):
        raise OperationalError("SELECT 1", {}, Exception("connection refused /var/lib/secret"))
    monkeypatch.setattr(pipeline_service, "list_runs", broken)
    r = client.get("/api/v1/runs", headers=engineer)
    assert r.status_code == 503 and "secret" not in r.text and "Traceback" not in r.text


def test_database_errors_in_stages_are_retryable():
    from app.recovery.workflow import is_retryable
    assert is_retryable(OperationalError("x", {}, Exception("reset")))
    assert not is_retryable(ValueError("bad"))


def test_reports_export_csv_and_json(client, engineer, baseline):
    csv = client.get("/api/v1/reports/pipeline_runs", params={"format": "csv"}, headers=engineer)
    assert csv.status_code == 200 and csv.text.startswith("run_id,")
    js = client.get("/api/v1/reports/incidents", params={"format": "json"}, headers=engineer)
    assert js.status_code == 200 and isinstance(js.json(), list)
    assert client.get("/api/v1/reports/unknown", headers=engineer).status_code == 404


def test_overview_metrics_come_from_records(client, engineer, db):
    from sqlalchemy import func, select
    from app.database.models import PipelineRun
    ov = client.get("/api/v1/analytics/overview", headers=engineer).json()
    assert ov["total_runs"] == db.scalar(select(func.count()).select_from(PipelineRun))


def test_security_headers_and_health(client):
    r = client.get("/health")
    assert r.json()["database"] is True
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"


def test_password_hashing():
    from app.security.authentication import hash_password, verify_password
    h = hash_password("Correct-horse-1")
    assert "Correct" not in h and verify_password("Correct-horse-1", h) and not verify_password("wrong", h)
