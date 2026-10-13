"""Apply database migrations and create reference data (default pipeline, bootstrap users).

Usage:  python scripts/init_db.py
"""
import _bootstrap  # noqa: F401

from app.config import get_settings
from app.database.connection import get_engine, init_db

if __name__ == "__main__":
    init_db()
    print(f"Database ready: {get_engine().url.render_as_string(hide_password=True)}")
    s = get_settings()
    users = [u for u in (s.bootstrap_admin_username, s.bootstrap_engineer_username, s.bootstrap_viewer_username) if u]
    print("Bootstrap users:", ", ".join(users) if users else "none (set BOOTSTRAP_* variables in .env)")
