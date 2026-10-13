"""Reference data required for the application to operate."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.models import Pipeline, User
from app.security.authentication import hash_password

logger = logging.getLogger("datapulse.seed")

DEFAULT_PIPELINE_NAME = "sales_daily"

SALES_PIPELINE_CONFIG = {
    "columns": {
        "transaction_id": {"type": "string", "required": True},
        "customer_id": {"type": "string", "required": True},
        "product_id": {"type": "string", "required": True},
        "quantity": {"type": "integer", "required": True, "min": 1},
        "unit_price": {"type": "float", "required": True, "min_exclusive": 0},
        "transaction_date": {"type": "date", "required": True},
        "region": {"type": "string", "required": True,
                   "allowed": ["North", "South", "East", "West", "Central"]},
    },
    "business_key": ["transaction_id"],
    "dedup_policy": "keep_first",
    "derived_columns": {"total_amount": "quantity * unit_price"},
}


def ensure_reference_data(session: Session) -> None:
    if session.scalar(select(Pipeline).where(Pipeline.name == DEFAULT_PIPELINE_NAME)) is None:
        session.add(Pipeline(name=DEFAULT_PIPELINE_NAME, source_type="csv",
                             description="Daily sales transactions (CSV or JSON) from the order system.",
                             config=SALES_PIPELINE_CONFIG))
        logger.info("Registered default pipeline '%s'", DEFAULT_PIPELINE_NAME)
    ensure_bootstrap_users(session)
    session.commit()


def ensure_bootstrap_users(session: Session) -> list[str]:
    """Create users defined in BOOTSTRAP_* environment variables if they do not exist."""
    s = get_settings()
    created = []
    for role, username, password in (("admin", s.bootstrap_admin_username, s.bootstrap_admin_password),
                                     ("engineer", s.bootstrap_engineer_username, s.bootstrap_engineer_password),
                                     ("viewer", s.bootstrap_viewer_username, s.bootstrap_viewer_password)):
        if not username or not password:
            continue
        if session.scalar(select(User).where(User.username == username)) is None:
            session.add(User(username=username, password_hash=hash_password(password), role=role))
            created.append(username)
    if created:
        logger.info("Created bootstrap users: %s", ", ".join(created))
    return created
