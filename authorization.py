"""Role-based access control.

Roles (least to most privileged):
  viewer   - read dashboards, incidents and aggregate metrics
  engineer - upload datasets, run pipelines, analyse incidents, request recovery
  admin    - everything, including approvals, data deletion, audit logs, index rebuilds
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.database.models import User
from app.security.authentication import get_current_user

ROLE_RANK = {"viewer": 0, "engineer": 1, "admin": 2}

PERMISSIONS: dict[str, str] = {
    "read": "viewer",
    "upload": "engineer",
    "run_pipeline": "engineer",
    "analyze_incident": "engineer",
    "update_incident": "engineer",
    "request_recovery": "engineer",
    "download_records": "engineer",
    "approve_recovery": "admin",
    "fault_injection": "engineer",
    "manage_pipelines": "admin",
    "delete_data": "admin",
    "view_audit": "admin",
    "rebuild_index": "admin",
}


def has_permission(user: User, permission: str) -> bool:
    required = PERMISSIONS[permission]
    return ROLE_RANK.get(user.role, -1) >= ROLE_RANK[required]


def require(permission: str) -> Callable[..., User]:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user, permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=f"Your role ({user.role}) is not allowed to perform '{permission}'.")
        return user
    return dependency


def permissions_for(user: User) -> list[str]:
    return sorted(p for p in PERMISSIONS if has_permission(user, p))
