"""LLM integration, fallbacks and RAG (required tests 14-16)."""
import json

import httpx
import pytest

from app.ai.diagnosis import analyze_incident
from app.ai.llm_client import LLMClient, LLMUnavailableError
from app.ai.rag import get_index
from app.config import get_settings
from app.database.models import Incident
from app.ingestion import sample_data as sd
from tests.conftest import incidents_for, upload_and_run


@pytest.fixture
def schema_incident(client, engineer, db, baseline):
    df = sd.generate_clean(2000, seed=61).rename(columns={"customer_id": "cust_id"})
    run = upload_and_run(client, engineer, "ai.csv", sd.to_csv_bytes(df))
    return db.get(Incident, incidents_for(client, engineer, run["id"])[0]["id"])


@pytest.fixture
def llm_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_api_key", "test-key")
    monkeypatch.setattr(s, "llm_model", "test-model")
    return s


def test_llm_unavailable_uses_labelled_fallback(client, engineer, schema_incident):
    r = client.post(f"/api/v1/incidents/{schema_incident.id}/analyze", headers=engineer).json()["ai_analysis"]
    assert r["source"] == "deterministic_fallback" and r["model"] is None
    assert r["llm_status"] == "not_configured"
    assert any("customer_id" in f for f in r["system_confirmed_facts"])
    chat = client.post("/api/v1/assistant/chat", headers=engineer,
                       json={"question": "Why did the pipeline fail?", "incident_id": schema_incident.id}).json()
    assert chat["mode"] == "deterministic" and "customer_id" in chat["answer"]


def test_llm_valid_response_is_validated_and_grounded(db, schema_incident, llm_on):
    reply = {"incident_summary": "Schema mismatch: customer_id missing.",
             "confirmed_evidence": ["Missing required columns: customer_id", "Input records: 2,000"],
             "probable_cause": "The column was probably renamed to cust_id upstream.",
             "recommended_action": "Confirm with the source owner, then apply_column_mapping.",
             "uncertainty": "The rename is inferred from name similarity.", "requires_manual_review": True,
             "referenced_documents": ["Missing Column Errors"]}

    def handler(request):
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    result = analyze_incident(db, schema_incident, LLMClient(transport=httpx.MockTransport(handler)))
    assert result["source"] == "llm" and result["model"] == "test-model"
    assert result["diagnosis"]["probable_cause"].startswith("The column")
    assert result["unverified_numbers"] == []


def test_llm_invented_numbers_are_flagged(db, schema_incident, llm_on):
    reply = {"incident_summary": "Run lost 98765 records.", "confirmed_evidence": ["98765 rows dropped"],
             "probable_cause": "Disk failure.", "recommended_action": "escalate", "uncertainty": "high",
             "requires_manual_review": True, "referenced_documents": []}
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]}))
    result = analyze_incident(db, schema_incident, LLMClient(transport=t))
    assert "98765" in result["unverified_numbers"]


def test_llm_invalid_json_falls_back(db, schema_incident, llm_on):
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}))
    result = analyze_incident(db, schema_incident, LLMClient(transport=t))
    assert result["source"] == "deterministic_fallback" and "llm_error" in result


def test_llm_rate_limit_retried_then_succeeds(llm_on):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "1"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    sleeps = []
    assert LLMClient(transport=httpx.MockTransport(handler), sleep=sleeps.append).complete("s", "u") == "ok"
    assert sleeps == [1.0]


def test_llm_timeout_and_server_errors_raise_unavailable(llm_on):
    def timeout(request):
        raise httpx.ReadTimeout("slow")
    with pytest.raises(LLMUnavailableError):
        LLMClient(transport=httpx.MockTransport(timeout), sleep=lambda s: None).complete("s", "u")
    with pytest.raises(LLMUnavailableError):
        LLMClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)), sleep=lambda s: None).complete("s", "u")


def test_anthropic_provider_format(llm_on, monkeypatch):
    monkeypatch.setattr(llm_on, "llm_provider", "anthropic")

    def handler(request):
        assert request.url.path.endswith("/messages") and request.headers["x-api-key"] == "test-key"
        return httpx.Response(200, json={"content": [{"type": "text", "text": "hello"}]})
    assert LLMClient(transport=httpx.MockTransport(handler)).complete("s", "u") == "hello"


def test_relevant_rag_retrieval():
    res = get_index().search("KeyError: 'customer_id' column missing after rename")
    assert res["relevant_found"] and res["hits"][0]["doc_id"] == "01_missing_column_errors"
    res = get_index().search("connection reset by the database server")
    assert res["hits"][0]["doc_id"] == "07_database_connection_errors"


def test_no_relevant_rag_document(client, engineer):
    res = get_index().search("best chocolate cake recipe")
    assert res["relevant_found"] is False and res["hits"] == []
    chat = client.post("/api/v1/assistant/chat", headers=engineer, json={"question": "chocolate cake recipe?"}).json()
    assert "could not find" in chat["answer"].lower()


def test_rag_index_rebuilds_when_files_missing():
    idx = get_index()
    idx.ensure_ready()
    for f in idx.dir.glob("*"):
        f.unlink()
    idx.embedder = None
    idx.ensure_ready()
    assert (idx.dir / "manifest.json").exists() and idx.search("duplicate records")["relevant_found"]


def test_assistant_answers_each_question_type(client, engineer, schema_incident):
    expected = {"Why did the pipeline fail?": "why", "Which validation checks failed?": "checks",
                "What changed compared with the previous run?": "changed", "How can this issue be resolved?": "resolve",
                "Has this happened before?": "history", "What does the documentation recommend?": "docs"}
    for q, intent in expected.items():
        r = client.post("/api/v1/assistant/chat", headers=engineer,
                        json={"question": q, "incident_id": schema_incident.id}).json()
        assert r["intent"] == intent and len(r["answer"]) > 20
