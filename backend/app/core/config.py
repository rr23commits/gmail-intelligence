from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from the repository-level .env file."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_secret_key: str | None = None
    database_url: str
    local_owner_email: str = "local-owner@localhost"
    local_owner_display_name: str = "Local Owner"


@lru_cache
def get_settings() -> Settings:
    return Settings()
