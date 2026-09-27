"""Two calendars that must not be mixed up.

- NYSE trading days (exchange_calendars XNYS) drive every price calculation.
- SEC business days (US federal holidays) drive filing-deadline checks.
They differ: NYSE closes on Good Friday (SEC open); SEC closes on Columbus Day and
Veterans Day (NYSE open).
"""

import bisect
from datetime import date, datetime, timedelta
from functools import cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import holidays
import pandas as pd

ET = ZoneInfo("America/New_York")


def now_et() -> datetime:
    return datetime.now(ET)


def to_et(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime; attach a timezone first")
    return dt.astimezone(ET)


@cache
def _xnys() -> xcals.ExchangeCalendar:
    # The default window is about today +/- 1 year; 12-month horizons need more.
    return xcals.get_calendar("XNYS", start="2005-01-03", end=f"{date.today().year + 5}-12-31")


@cache
def _sessions() -> tuple[list[date], dict[date, int]]:
    days = [ts.date() for ts in _xnys().sessions]
    return days, {d: i for i, d in enumerate(days)}


def is_trading_day(d: date) -> bool:
    return d in _sessions()[1]


def next_trading_day(d: date) -> date:
    days, _ = _sessions()
    return days[bisect.bisect_right(days, d)]


def prev_trading_day(d: date) -> date:
    days, _ = _sessions()
    return days[bisect.bisect_left(days, d) - 1]


def add_trading_days(d: date, n: int) -> date:
    days, index = _sessions()
    if d not in index:
        raise ValueError(f"{d} is not a trading day")
    return days[index[d] + n]


def trading_days(start: date, end: date) -> list[date]:
    days, _ = _sessions()
    return days[bisect.bisect_left(days, start) : bisect.bisect_right(days, end)]


def trading_days_between(a: date, b: date) -> int:
    """Number of sessions s with a < s <= b (0 when b <= a)."""
    if b <= a:
        return 0
    days, _ = _sessions()
    return bisect.bisect_right(days, b) - bisect.bisect_right(days, a)


def session_open_close(d: date) -> tuple[datetime, datetime]:
    cal = _xnys()
    ts = pd.Timestamp(d)
    opened = cal.session_open(ts).tz_convert(ET).to_pydatetime()
    closed = cal.session_close(ts).tz_convert(ET).to_pydatetime()
    return opened, closed


@cache
def _sec_holidays() -> holidays.HolidayBase:
    return holidays.country_holidays("US", years=range(2005, 2036))


def is_sec_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _sec_holidays()


def add_sec_business_days(d: date, n: int) -> date:
    current, remaining = d, n
    while remaining > 0:
        current += timedelta(days=1)
        if is_sec_business_day(current):
            remaining -= 1
    return current


def sec_business_days_between(a: date, b: date) -> int:
    """Number of SEC business days d with a < d <= b (0 when b <= a)."""
    count, current = 0, a
    while current < b:
        current += timedelta(days=1)
        if is_sec_business_day(current):
            count += 1
    return count
