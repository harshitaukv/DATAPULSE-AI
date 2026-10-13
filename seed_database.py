"""Seed a demonstration baseline by running real pipeline executions on synthetic data.

Every seeded run goes through the actual ETL, quality, monitoring and storage
code; nothing is inserted directly into the dashboard tables. Seeded runs are
marked trigger_type='seed' and their datasets are flagged as synthetic.

Usage:  python scripts/seed_database.py [--days 14] [--force]
"""
import argparse

import _bootstrap  # noqa: F401
from sqlalchemy import func, select

from app.database.connection import get_session_factory, init_db
from app.database.models import Pipeline, PipelineRun
from app.database.seed import DEFAULT_PIPELINE_NAME
from app.ingestion.sample_data import daily_history_frames, to_csv_bytes
from app.services.dataset_service import store_upload
from app.services.pipeline_service import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14, help="number of synthetic daily batches")
    parser.add_argument("--force", action="store_true", help="seed even if runs already exist")
    args = parser.parse_args()

    init_db()
    with get_session_factory()() as db:
        pipeline = db.scalar(select(Pipeline).where(Pipeline.name == DEFAULT_PIPELINE_NAME))
        existing = db.scalar(select(func.count()).select_from(PipelineRun)
                             .where(PipelineRun.pipeline_id == pipeline.id)) or 0
        if existing and not args.force:
            print(f"Pipeline already has {existing} runs; use --force to add more seed runs.")
            return
        for day, frame in daily_history_frames(args.days):
            ds, _ = store_upload(db, f"synthetic_daily_sales_{day.isoformat()}.csv", to_csv_bytes(frame), None,
                                 is_synthetic=True)
            run = run_pipeline(db, pipeline, ds, None, trigger_type="seed")
            print(f"  {day}  {run.input_records:>6,} records  status={run.status:<9} "
                  f"quality={run.quality_score}  anomaly={run.anomaly.get('status')}")
    print(f"Seeded {args.days} synthetic baseline runs through the real pipeline.")


if __name__ == "__main__":
    main()
