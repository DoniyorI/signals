from datetime import date

import pytest
from pydantic import ValidationError

from signals.config import Settings


def test_requires_sec_user_agent(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_rejects_user_agent_without_email():
    with pytest.raises(ValidationError):
        Settings(sec_user_agent="Doniyor", _env_file=None)  # pyright: ignore[reportCallIssue]


def test_defaults():
    s = Settings(sec_user_agent="Test User test@example.com", _env_file=None)  # pyright: ignore[reportCallIssue]
    assert s.sec_rate_limit == 8.0
    assert s.backfill_start == date(2016, 1, 1)
    assert s.form144_start == date(2023, 4, 13)
    assert s.stakes_start == date(2024, 12, 18)
    assert (s.tracked_funds_top_n, s.tracked_funds_max_positions) == (500, 300)
    assert (s.price_primary, s.alpaca_feed) == ("alpaca", "sip")
