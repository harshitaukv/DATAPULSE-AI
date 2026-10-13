"""Isolation Forest anomaly detection over run-level monitoring features.

The model identifies *unusual combinations* of metrics (volume, missing rate,
duplicates, invalid rate, duration, deviation). It does not determine causes;
the incident investigation layer does that from the measured evidence.
"""
from __future__ import annotations

import logging
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from app.monitoring.metrics import FEATURE_NAMES

logger = logging.getLogger("datapulse.anomaly")


class AnomalyDetector:
    def __init__(self, contamination: float | str = "auto", random_state: int = 42):
        self.contamination = contamination
        self.random_state = random_state
        self.scaler: StandardScaler | None = None
        self.model: IsolationForest | None = None
        self.n_train = 0

    def fit(self, features: list[list[float]]) -> "AnomalyDetector":
        X = np.asarray(features, dtype=float)
        self.scaler = StandardScaler().fit(X)
        # Guard against zero variance columns (e.g. always-0 duplicate rate in clean history)
        self.scaler.scale_ = np.where(self.scaler.scale_ < 1e-6, 1.0, self.scaler.scale_)
        self.model = IsolationForest(n_estimators=200, contamination=self.contamination,
                                     random_state=self.random_state).fit(self.scaler.transform(X))
        self.n_train = len(X)
        return self

    def score(self, feature: list[float]) -> dict:
        assert self.model is not None and self.scaler is not None
        x = self.scaler.transform(np.asarray([feature], dtype=float))
        decision = float(self.model.decision_function(x)[0])
        z = x[0]
        contributors = sorted(
            ({"feature": name, "z_score": round(float(v), 2)} for name, v in zip(FEATURE_NAMES, z)),
            key=lambda d: abs(d["z_score"]), reverse=True)[:3]
        return {"decision_score": round(decision, 4), "is_anomaly": decision < 0,
                "top_deviating_features": contributors}

    def save(self, path: Path) -> None:
        joblib.dump({"scaler": self.scaler, "model": self.model, "n_train": self.n_train,
                     "contamination": self.contamination}, path)

    @classmethod
    def load(cls, path: Path) -> "AnomalyDetector":
        data = joblib.load(path)
        det = cls(contamination=data["contamination"])
        det.scaler, det.model, det.n_train = data["scaler"], data["model"], data["n_train"]
        return det


def _contamination() -> float | str:
    from app.config import get_settings
    value = get_settings().iforest_contamination
    return "auto" if value == "auto" else float(value)


def detect(pipeline_id: int, history: list[list[float]], current: list[float], *,
           min_history: int, models_dir: Path) -> dict:
    """Score the current run against the pipeline's own history.

    Returns a dict with method/status. With insufficient history the run is
    explicitly *not* flagged rather than guessed at.
    """
    if len(history) < min_history:
        return {"method": "isolation_forest", "status": "insufficient_history",
                "history_size": len(history), "required": min_history, "is_anomaly": False}
    path = models_dir / f"pipeline_{pipeline_id}_iforest.joblib"
    detector = None
    if path.exists():
        try:
            cached = AnomalyDetector.load(path)
            if cached.n_train == len(history) and cached.contamination == _contamination():
                detector = cached
        except Exception:  # corrupted or incompatible model file: retrain
            logger.warning("Could not load cached model %s; retraining", path.name)
    if detector is None:
        detector = AnomalyDetector(contamination=_contamination()).fit(history)
        detector.save(path)
    result = detector.score(current)
    result.update({"method": "isolation_forest", "status": "evaluated", "history_size": len(history)})
    return result
