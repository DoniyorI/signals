"""Application settings, read from environment variables and `.env`."""

from datetime import date
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://signals:signals@127.0.0.1:5432/signals"
    sec_user_agent: str
    sec_rate_limit: float = 8.0
    raw_archive_dir: Path = Path("data/raw")
    backfill_start: date = date(2016, 1, 1)
    form144_start: date = date(2023, 4, 13)
    stakes_start: date = date(2024, 12, 18)
    price_primary: Literal["alpaca", "yfinance"] = "alpaca"
    alpaca_api_key: str | None = None
    alpaca_secret_key: SecretStr | None = None
    alpaca_feed: Literal["sip", "iex"] = "sip"
    alpaca_data_url: str = "https://data.alpaca.markets"
    openfigi_api_key: SecretStr | None = None
    tracked_funds_top_n: int = 500
    tracked_funds_max_positions: int = 300
    log_json: bool = True

    @field_validator("sec_user_agent")
    @classmethod
    def _user_agent_has_contact(cls, value: str) -> str:
        # SEC fair-access rules require a name and an email address.
        if " " not in value.strip() or "@" not in value:
            raise ValueError("SEC_USER_AGENT must be 'Name email@domain'")
        return value.strip()


@cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
