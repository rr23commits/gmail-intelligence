from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from the repository-level .env file."""

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_secret_key: str
    database_url: str
    token_encryption_key: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
