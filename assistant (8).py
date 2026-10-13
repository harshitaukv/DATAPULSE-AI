"""AI assistant and knowledge-base endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.ai import assistant as assistant_service
from app.ai.llm_client import LLMClient
from app.ai.rag import get_index
from app.api.deps import get_or_404
from app.config import get_settings
from app.database.connection import get_db
from app.database.models import Incident, User
from app.schemas import ChatRequest
from app.security.audit import record_audit
from app.security.authorization import require

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


@router.post("/chat")
def chat(body: ChatRequest, request: Request, db: Session = Depends(get_db),
         user: User = Depends(require("read"))):
    incident = get_or_404(db, Incident, body.incident_id, "Incident") if body.incident_id else None
    result = assistant_service.chat(db, body.question, incident, [m.model_dump() for m in body.history])
    record_audit(db, "assistant_chat", user=user, resource_type="incident", resource_id=body.incident_id or "",
                 details={"intent": result["intent"], "mode": result["mode"]}, request=request)
    return result


@router.get("/search")
def search(q: str = Query(..., min_length=2, max_length=500), k: int = Query(4, ge=1, le=10),
           _: User = Depends(require("read"))):
    return get_index().search(q, k)


@router.get("/status")
def status(_: User = Depends(require("read"))):
    s = get_settings()
    client = LLMClient()
    return {"llm": {"configured": client.configured, "provider": s.llm_provider if client.configured else None,
                    "model": s.llm_model if client.configured else None,
                    "mode": "llm" if client.configured else "deterministic_fallback"},
            "rag": get_index().status()}


@router.post("/rebuild-index")
def rebuild(request: Request, db: Session = Depends(get_db), admin: User = Depends(require("rebuild_index"))):
    manifest = get_index().build()
    record_audit(db, "rebuild_rag_index", user=admin, resource_type="rag_index", details=manifest, request=request)
    return manifest
