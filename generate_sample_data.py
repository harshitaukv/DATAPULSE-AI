"""Write the synthetic sample datasets to data/sample/.

Usage:  python scripts/generate_sample_data.py
All files are synthetic and prefixed with 'synthetic_'.
"""
import _bootstrap  # noqa: F401

from app.config import get_settings
from app.ingestion.sample_data import SAMPLES, generate_all

if __name__ == "__main__":
    target = get_settings().sample_dir
    for name in generate_all(target):
        desc = next(s.description for s in SAMPLES if s.filename == name)
        print(f"  {name:<45} {desc}")
    print(f"Synthetic datasets written to {target}")
