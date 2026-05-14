"""Application settings loaded from environment / .env file."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration — values come from env-vars or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram ---
    bot_token: str

    # --- Database ---
    database_url: str = "postgresql+asyncpg://bot:bot_password@db:5432/gas_equipment"

    # --- Logging ---
    log_level: str = "INFO"


settings = Settings()  # type: ignore[call-arg]
