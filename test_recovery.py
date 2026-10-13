"""Recovery, retries and authorisation (required tests 12, 13, 17, 20)."""
import uuid

from app.ingestion import sample_data as sd
from app.processing.errors import TransientError
from app.recovery.workflow import FaultInjector, RetryPolicy, WorkflowEngine
from tests.conftest import clear_repeated_failures, incident, incidents_for, upload, upload_and_run


def test_transient_failure_recovers_with_backoff(client, engineer, baseline):
    run = upload_and_run(client, engineer, "t1.csv", sd.to_csv_bytes(sd.generate_clean(3000, seed=41)),
                         fault_injection={"stage": "load", "fail_times": 2})
    assert run["status"] != "failed"
    load = next(s for s in run["stage_log"] if s["name"] == "load")
    assert [a["status"] for a in load["attempts"]] == ["failed", "failed", "succeeded"]
    delays = [a["retry_delay_seconds"] for a in load["attempts"][:2]]
    assert delays[1] == delays[0] * 2  # exponential backoff
    inc = next(i for i in incidents_for(client, engineer, run["id"]) if i["rule_id"] == "RUNTIME_TRANSIENT")
    assert inc["status"] == "resolved" and "output validated" in inc["resolution_notes"]
    assert inc["evidence"]["simulated"] is True


def test_retry_limit_enforced_and_escalated(client, engineer, baseline):
    run = upload_and_run(client, engineer, "t3.csv", sd.to_csv_bytes(sd.generate_clean(3000, seed=42)),
                         fault_injection={"stage": "load", "fail_times": 3})
    assert run["status"] == "failed" and run["failed_stage"] == "load"
    load = next(s for s in run["stage_log"] if s["name"] == "load")
    assert len(load["attempts"]) == 3  # 1 attempt + max_retries (2)
    inc = next(i for i in incidents_for(client, engineer, run["id"]) if i["rule_id"] == "RUNTIME_TRANSIENT")
    logs = client.get("/api/v1/recovery-logs", params={"incident_id": inc["id"]}, headers=engineer).json()["items"]
    assert any(l["action"] == "escalate" and l["result"] == "requires_manual" for l in logs)


def test_non_retryable_errors_are_not_retried():
    calls = []
    engine = WorkflowEngine([("validate", lambda ctx: calls.append(1))], RetryPolicy(2, 0),
                            sleep=lambda s: None, fault=FaultInjector("validate", 5, kind="non_retryable"))
    outcome = engine.run(None)
    assert outcome.status == "failed" and len(outcome.stages[0].attempts) == 1 and calls == []


def test_workflow_engine_backoff_schedule():
    sleeps = []
    engine = WorkflowEngine([("load", lambda ctx: None)], RetryPolicy(3, 0.5, 2.0), sleep=sleeps.append,
                            fault=FaultInjector("load", 3))
    assert engine.run(None).status == "succeeded"
    assert sleeps == [0.5, 1.0, 2.0]


def test_manual_retry_after_exhausted_retries(client, admin, baseline):
    clear_repeated_failures(client, admin)
    run = upload_and_run(client, admin, "t4.csv", sd.to_csv_bytes(sd.generate_clean(3000, seed=43)),
                         fault_injection={"stage": "load", "fail_times": 3})
    inc = next(i for i in incidents_for(client, admin, run["id"]) if i["rule_id"] == "RUNTIME_TRANSIENT")
    first = client.post(f"/api/v1/incidents/{inc['id']}/recover", json={"action": "retry_run"}, headers=admin)
    assert first.status_code == 200 and first.json()["result"] == "success"
    assert client.get(f"/api/v1/incidents/{inc['id']}", headers=admin).json()["status"] == "resolved"


def test_viewer_cannot_recover_or_upload(client, viewer, engineer, baseline):
    run = upload_and_run(client, engineer, "v.csv", sd.to_csv_bytes(sd.generate_clean(300, seed=44)))
    inc = incidents_for(client, engineer, run["id"])[0]
    r = client.post(f"/api/v1/incidents/{inc['id']}/recover", json={"action": "escalate"}, headers=viewer)
    assert r.status_code == 403
    assert upload(client, viewer, "x.csv", b"a\n1\n").status_code == 403
    assert client.get("/api/v1/incidents", headers=viewer).status_code == 200


def test_column_mapping_requires_admin_approval(client, engineer, admin, baseline):
    df = sd.generate_clean(5000, seed=45).rename(columns={"customer_id": "cust_id"})
    run = upload_and_run(client, engineer, "renamed.csv", sd.to_csv_bytes(df))
    inc = incident(client, engineer, run["id"], "SCHEMA_MISSING_COLUMNS")
    assert inc["evidence"]["suggested_mappings"]["cust_id"]["maps_to"] == "customer_id"
    req = client.post(f"/api/v1/incidents/{inc['id']}/recover", headers=engineer,
                      json={"action": "apply_column_mapping", "column_mapping": {"cust_id": "customer_id"}}).json()
    assert req["approval_status"] == "pending" and req["result"] == "pending"
    assert client.post(f"/api/v1/recovery-logs/{req['id']}/decision", json={"approve": True},
                       headers=engineer).status_code == 403
    done = client.post(f"/api/v1/recovery-logs/{req['id']}/decision", json={"approve": True}, headers=admin).json()
    assert done["result"] == "success" and done["approval_status"] == "approved"
    assert done["details"]["output_validation"] == "passed"
    assert client.get(f"/api/v1/incidents/{inc['id']}", headers=admin).json()["status"] == "resolved"


def test_invalid_recovery_requests(client, admin, baseline):
    df = sd.generate_clean(3000, seed=46).rename(columns={"customer_id": "cust_id"})
    run = upload_and_run(client, admin, "bad_req.csv", sd.to_csv_bytes(df))
    inc_id = incident(client, admin, run["id"], "SCHEMA_MISSING_COLUMNS")["id"]
    url = f"/api/v1/incidents/{inc_id}/recover"
    assert client.post(url, json={"action": "retry_run"}, headers=admin).status_code == 400  # not in policy
    assert client.post(url, json={"action": "rm -rf /"}, headers=admin).status_code == 422  # not an action
    assert client.post(url, json={"action": "apply_column_mapping", "column_mapping": {"nope": "customer_id"}},
                       headers=admin).status_code == 400
    assert client.post(url, json={"action": "apply_column_mapping", "column_mapping": {"cust_id": "password"}},
                       headers=admin).status_code == 400
    assert client.post(url, json={"action": "rerun_with_dataset", "dataset_id": str(uuid.uuid4())},
                       headers=admin).status_code == 400
    ok = client.post(url, json={"action": "apply_column_mapping", "column_mapping": {"cust_id": "customer_id"}},
                     headers=admin)
    assert ok.status_code == 200
    again = client.post(url, json={"action": "escalate"}, headers=admin)
    assert again.status_code == 409  # already resolved


def test_idempotent_recovery_request(client, admin, baseline):
    run = upload_and_run(client, admin, "idem.csv", sd.to_csv_bytes(sd.generate_clean(300, seed=47)))
    inc_id = incidents_for(client, admin, run["id"])[0]["id"]
    body = {"action": "escalate", "idempotency_key": "key-" + uuid.uuid4().hex[:12]}
    a = client.post(f"/api/v1/incidents/{inc_id}/recover", json=body, headers=admin).json()
    b = client.post(f"/api/v1/incidents/{inc_id}/recover", json=body, headers=admin).json()
    assert a["id"] == b["id"]


def test_repeated_failures_suspend_automatic_retries(client, admin, baseline):
    clear_repeated_failures(client, admin)
    for i in range(3):
        df = sd.generate_clean(500, seed=70 + i).drop(columns=["region"])
        last = upload_and_run(client, admin, f"broken_{i}.csv", sd.to_csv_bytes(df))
    rep = incident(client, admin, last["id"], "REPEATED_FAILURE")
    assert rep["severity"] == "critical"
    run = upload_and_run(client, admin, "after.csv", sd.to_csv_bytes(sd.generate_clean(3000, seed=79)),
                         fault_injection={"stage": "load", "fail_times": 1})
    load = next(s for s in run["stage_log"] if s["name"] == "load")
    assert run["status"] == "failed" and len(load["attempts"]) == 1  # no automatic retry while suspended
    inc = incident(client, admin, run["id"], "RUNTIME_TRANSIENT")
    assert "retry_run" not in client.get(f"/api/v1/incidents/{inc['id']}", headers=admin).json()["eligible_actions"]
    clear_repeated_failures(client, admin)
