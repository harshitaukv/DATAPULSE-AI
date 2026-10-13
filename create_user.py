"""Create a user interactively (password is never echoed or stored in plain text).

Usage:  python scripts/create_user.py <username> <admin|engineer|viewer>
"""
import getpass
import sys

import _bootstrap  # noqa: F401
from sqlalchemy import select

from app.database.connection import get_session_factory, init_db
from app.database.models import User
from app.security.authentication import hash_password, validate_password_strength

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] not in ("admin", "engineer", "viewer"):
        sys.exit(__doc__)
    username, role = sys.argv[1], sys.argv[2]
    password = getpass.getpass("Password: ")
    validate_password_strength(password)
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    init_db()
    with get_session_factory()() as db:
        if db.scalar(select(User).where(User.username == username)):
            sys.exit("User already exists.")
        db.add(User(username=username, password_hash=hash_password(password), role=role))
        db.commit()
    print(f"Created {role} '{username}'.")
