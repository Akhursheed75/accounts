"""Application configuration, sourced entirely from environment variables."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Reconcilia"
    environment: str = "development"
    debug: bool = False

    # --- database -------------------------------------------------------
    database_url: str = "postgresql+psycopg://reconcilia:reconcilia@localhost:5432/reconcilia"

    # --- auth -----------------------------------------------------------
    secret_key: str = "change-me-in-production"
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    cookie_secure: bool = False
    cookie_domain: str | None = None
    cookie_samesite: str = "lax"

    # --- files ----------------------------------------------------------
    storage_backend: str = "local"          # local | s3 (s3 adapter is a stub)
    storage_root: str = "./storage"
    max_upload_bytes: int = 25 * 1024 * 1024
    allowed_upload_types: str = "application/pdf"

    # --- ocr ------------------------------------------------------------
    ocr_dpi: int = 300
    ocr_languages: str = "eng+spa"
    tesseract_cmd: str | None = None

    # Reading photos of the handwritten daily sheet. Optional: without a key the
    # photo is still kept with the sheet and shown beside the form.
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    sheet_reader_model: str = "claude-sonnet-5-5"
    sheet_reader_timeout: int = 120
    max_photo_bytes: int = 15 * 1024 * 1024
    poppler_path: str | None = None

    # --- reconciliation defaults ---------------------------------------
    default_date_window_days: int = 3
    default_auto_confirm_score: int = 95
    default_suggest_score: int = 60

    # --- misc -----------------------------------------------------------
    cors_origins: str = "http://localhost:3000"
    seed_demo_data: bool = True
    worker_poll_seconds: float = 2.0

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_root).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_upload_type_list(self) -> list[str]:
        return [t.strip() for t in self.allowed_upload_types.split(",") if t.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
