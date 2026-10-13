"""Test configuration: isolated SQLite database and data directory per test session."""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="datapulse_test_"))
os.environ.update({
    "APP_ENV": "test",
    "DATA_DIR": str(TMP),
    "DATABASE_URL": os.getenv("TEST_DATABASE_URL", f"sqlite:///{TMP / 'test.db'}"),
    "SECRET_KEY": "test-secret-key-not-for-production-0123456789",
    "EMBEDDING_BACKEND": "tfidf",
    "RETRY_BASE_DELAY_SECONDS": "0.001",
    "LLM_API_KEY": "", "LLM_MODEL": "",
    "BOOTSTRAP_ADMIN_USERNAME": "admin", "BOOTSTRAP_ADMIN_PASSWORD": "Admin-test-123",
    "BOOTSTRAP_ENGINEER_USERNAME": "engineer", "BOOTSTRAP_ENGINEER_PASSWORD": "Engineer-test-123",
    "BOOTSTRAP_VIEWER_USERNAME": "viewer", "BOOTSTRAP_VIEWER_PASSWORD": "Viewer-test-123",
    "MAX_UPLOAD_MB": "2",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database.connection import get_session_factory  # noqa: E402
from app.database.models import Pipeline  # noqa: E402
from app.ingestion import sample_data as sd  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _token(client, user, pw):
    r = client.post("/api/v1/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return _token(client, "admin", "Admin-test-123")


@pytest.fixture(scope="session")
def engineer(client):
    return _token(client, "engineer", "Engineer-test-123")


@pytest.fixture(scope="session")
def viewer(client):
    return _token(client, "viewer", "Viewer-test-123")


@pytest.fixture(scope="session")
def db():
    session = get_session_factory()()
    yield session
    session.close()


@pytest.fixture(scope="session")
def baseline(client, engineer):
    """Twelve clean synthetic daily runs so volume baselines and Isolation Forest are active."""
    run_ids = []
    for day, frame in sd.daily_history_frames(12, seed=300):
        ds = upload(client, engineer, f"synthetic_base_{day}.csv", sd.to_csv_bytes(frame)).json()["dataset"]
        run_ids.append(run(client, engineer, ds["id"]).json()["id"])
    return run_ids


def upload(client, headers, name, content: bytes, mime="text/csv"):
    return client.post("/api/v1/uploads", files={"file": (name, content, mime)}, headers=headers)


def run(client, headers, dataset_id, **extra):
    return client.post("/api/v1/pipelines/1/runs", json={"dataset_id": dataset_id, **extra}, headers=headers)


def upload_and_run(client, headers, name, content, **extra):
    ds = upload(client, headers, name, content)
    assert ds.status_code == 201, ds.text
    r = run(client, headers, ds.json()["dataset"]["id"], **extra)
    assert r.status_code == 201, r.text
    return r.json()


def incidents_for(client, headers, run_id):
    return client.get("/api/v1/incidents", params={"run_id": run_id}, headers=headers).json()["items"]


def incident(client, headers, run_id, rule_id):
    return next(i for i in incidents_for(client, headers, run_id) if i["rule_id"] == rule_id)


def clear_repeated_failures(client, admin):
    """Close repeated-failure incidents (as a reviewer would) and add clean runs to reset the window."""
    for inc in client.get("/api/v1/incidents", params={"status": "open,under_review", "limit": 500},
                          headers=admin).json()["items"]:
        if inc["rule_id"] == "REPEATED_FAILURE":
            client.patch(f"/api/v1/incidents/{inc['id']}", json={"status": "closed", "resolution_notes": "reviewed"},
                         headers=admin)
    for i in range(5):
        upload_and_run(client, admin, f"reset_{i}.csv", sd.to_csv_bytes(sd.generate_clean(5000, seed=990 + i)))
