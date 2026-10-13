"""Audit trail: who did what, to which resource, with what outcome."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.database.models import AuditLog, User

logger = logging.getLogger("datapulse.audit")


def record_audit(db: Session, action: str, *, user: User | None = None, resource_type: str = "",
                 resource_id: Any = "", outcome: str = "success", details: dict | None = None,
                 request: Request | None = None, commit: bool = True) -> AuditLog:
    ip = ""
    if request is not None and request.client is not None:
        ip = request.client.host
    entry = AuditLog(user_id=user.id if user else None, username=user.username if user else "system",
                     action=action, resource_type=resource_type, resource_id=str(resource_id or ""),
                     outcome=outcome, ip_address=ip, details=details or {})
    db.add(entry)
    if commit:
        db.commit()
    logger.info("audit action=%s user=%s resource=%s:%s outcome=%s", action,
                entry.username, resource_type, resource_id, outcome)
    return entry
