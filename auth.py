"""Authentication endpoints with basic brute-force protection."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.schemas import LoginRequest, TokenResponse, UserCreate, UserOut
from app.security.audit import record_audit
from app.security.authentication import (authenticate, create_access_token, get_current_user, hash_password,
                                         validate_password_strength)
from app.security.authorization import permissions_for, require

router = APIRouter(prefix="/api/v1", tags=["auth"])

_FAILED: dict[str, deque] = defaultdict(deque)
MAX_FAILURES, WINDOW_SECONDS = 5, 300


def _throttled(key: str) -> bool:
    q, now = _FAILED[key], time.monotonic()
    while q and now - q[0] > WINDOW_SECONDS:
        q.popleft()
    return len(q) >= MAX_FAILURES


def user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.permissions = permissions_for(user)
    return out


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    key = body.username.lower()
    if _throttled(key):
        record_audit(db, "login", resource_type="user", resource_id=body.username, outcome="blocked",
                     request=request, details={"reason": "too many failed attempts"})
        raise HTTPException(429, "Too many failed sign-in attempts. Wait five minutes and try again.")
    user = authenticate(db, body.username, body.password)
    if user is None:
        _FAILED[key].append(time.monotonic())
        record_audit(db, "login", resource_type="user", resource_id=body.username, outcome="denied", request=request)
        raise HTTPException(401, "Incorrect username or password.")
    _FAILED.pop(key, None)
    token, expires = create_access_token(user)
    record_audit(db, "login", user=user, resource_type="user", resource_id=user.id, request=request)
    return TokenResponse(access_token=token, expires_in=expires, user=user_out(user))


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require("manage_pipelines"))):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(require("manage_pipelines"))):
    try:
        validate_password_strength(body.password)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "A user with that username already exists.")
    user = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(user)
    db.commit()
    record_audit(db, "create_user", user=admin, resource_type="user", resource_id=user.id,
                 details={"username": user.username, "role": user.role}, request=request)
    return user_out(user)
