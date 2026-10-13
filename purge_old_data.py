"""Apply the data-retention policy (RETENTION_DAYS) to stored datasets and outputs.

Usage:  python scripts/purge_old_data.py            # dry run
        python scripts/purge_old_data.py --apply    # delete files
"""
import argparse

import _bootstrap  # noqa: F401

from app.config import get_settings
from app.database.connection import get_session_factory
from app.services.retention import apply_retention

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with get_session_factory()() as db:
        print(apply_retention(db, get_settings().retention_days, dry_run=not args.apply))
