from datetime import date, time

from signals.domain import calendars as c


def test_good_friday_sec_open_market_closed():
    assert c.is_trading_day(date(2024, 3, 29)) is False
    assert c.is_sec_business_day(date(2024, 3, 29)) is True


def test_columbus_day_market_open_sec_closed():
    assert c.is_trading_day(date(2024, 10, 14)) is True
    assert c.is_sec_business_day(date(2024, 10, 14)) is False


def test_juneteenth_and_observed_july_fourth():
    assert not c.is_trading_day(date(2024, 6, 19))
    assert not c.is_sec_business_day(date(2024, 6, 19))
    assert c.is_sec_business_day(date(2026, 7, 3)) is False


def test_trading_day_arithmetic():
    assert c.next_trading_day(date(2024, 3, 28)) == date(2024, 4, 1)
    assert c.prev_trading_day(date(2024, 4, 1)) == date(2024, 3, 28)
    assert c.add_trading_days(date(2024, 1, 2), 21) == date(2024, 2, 1)
    assert c.trading_days_between(date(2024, 1, 2), date(2024, 1, 10)) == 6


def test_early_close_day_after_thanksgiving():
    open_, close = c.session_open_close(date(2024, 11, 29))
    assert (open_.time(), close.time()) == (time(9, 30), time(13, 0))
    assert open_.tzinfo is not None


def test_sec_business_day_arithmetic():
    assert c.sec_business_days_between(date(2024, 10, 10), date(2024, 10, 16)) == 3
    assert c.add_sec_business_days(date(2024, 10, 11), 2) == date(2024, 10, 16)
