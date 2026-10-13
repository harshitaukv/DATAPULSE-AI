"""Application configuration.

All settings are read from environment variables (or a `.env` file in the
project root). Nothing secret is hardcoded: development fallbacks are generated
at runtime and clearly logged, and production mode refuses to start without
explicit secrets.
"""
from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger("datapulse.config")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -------------------------------------------------------
    app_name: str = "DataPulse AI"
    app_env: str = Field(default="development", description="development | test | production")
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:8501,http://127.0.0.1:8501"

    # --- Storage -----------------------------------------------------------
    database_url: str = ""  # empty -> SQLite fallback under DATA_DIR
    data_dir: Path = PROJECT_ROOT / "data"
    knowledge_base_dir: Path = PROJECT_ROOT / "knowledge_base" / "troubleshooting_guides"
    auto_migrate: bool = True

    # --- Security ----------------------------------------------------------
    secret_key: str = ""
    data_encryption_key: str = ""
    access_token_expire_minutes: int = 480
    max_upload_mb: float = 20.0
    retention_days: int = 90
    bootstrap_admin_username: str = ""
    bootstrap_admin_password: str = ""
    bootstrap_engineer_username: str = ""
    bootstrap_engineer_password: str = ""
    bootstrap_viewer_username: str = ""
    bootstrap_viewer_password: str = ""
    sensitive_columns: str = "customer_id"

    # --- Data-quality thresholds (fractions, not percentages) --------------
    duplicate_rate_threshold: float = 0.02
    missing_rate_threshold: float = 0.05
    invalid_rate_threshold: float = 0.02
    volume_drop_threshold: float = 0.50   # -50% vs baseline median
    volume_spike_threshold: float = 1.00  # +100% vs baseline median
    duration_factor_threshold: float = 3.0
    duration_min_seconds: float = 2.0
    min_history_for_baseline: int = 5
    min_history_for_ml: int = 10
    baseline_window: int = 30
    repeated_failure_count: int = 3
    repeated_failure_window: int = 5
    truncation_missing_fraction: float = 0.5
    iforest_contamination: str = "0.02"  # "auto" or a fraction; 0.02 chosen by ablation (docs/evaluation_results.md)

    # --- Recovery ----------------------------------------------------------
    max_retries: int = 2
    retry_base_delay_seconds: float = 0.5
    retry_backoff_factor: float = 2.0
    enable_fault_injection: bool = True

    # --- Generative AI -----------------------------------------------------
    llm_provider: str = "openai_compatible"  # openai_compatible | anthropic
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_max_output_tokens: int = 900

    # --- RAG ---------------------------------------------------------------
    embedding_backend: str = "auto"  # auto | sentence_transformers | tfidf
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    rag_top_k: int = 4
    rag_min_score_st: float = 0.30
    rag_min_score_tfidf: float = 0.08
    chunk_max_chars: int = 900

    # ----------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'datapulse.db').as_posix()}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def sample_dir(self) -> Path:
        return self.data_dir / "sample"

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sensitive_column_list(self) -> list[str]:
        return [c.strip() for c in self.sensitive_columns.split(",") if c.strip()]

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key and self.llm_model)

    def ensure_directories(self) -> None:
        for d in (self.data_dir, self.uploads_dir, self.processed_dir, self.reports_dir,
                  self.index_dir, self.models_dir, self.sample_dir):
            d.mkdir(parents=True, exist_ok=True)

    def finalize_secrets(self) -> None:
        """Fill development-only secrets, refuse to run production without real ones."""
        if self.is_production:
            missing = [n for n, v in (("SECRET_KEY", self.secret_key),
                                      ("DATA_ENCRYPTION_KEY", self.data_encryption_key),
                                      ("DATABASE_URL", self.database_url)) if not v]
            if missing:
                raise RuntimeError(f"Production mode requires: {', '.join(missing)}")
            return

        if not self.secret_key:
            self.secret_key = secrets.token_urlsafe(48)
            logger.warning("SECRET_KEY not set: generated an ephemeral development key. "
                           "Tokens will be invalidated on restart.")
        if not self.data_encryption_key:
            key_file = self.data_dir / ".dev_encryption_key"
            if key_file.exists():
                self.data_encryption_key = key_file.read_text().strip()
            else:
                self.data_encryption_key = Fernet.generate_key().decode()
                key_file.write_text(self.data_encryption_key)
            logger.warning("DATA_ENCRYPTION_KEY not set: using a development key stored in "
                           "data/.dev_encryption_key. Set DATA_ENCRYPTION_KEY for real deployments.")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    settings.finalize_secrets()
    return settings
