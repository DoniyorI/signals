"""Entry prices on the adjusted scale (spec 9.2).

- Executed basis: the insider's own first-day VWAP times that date's `adj_factor`; the
  session close (flagged) when the price is missing or zero.
- Filed basis: the first tradable price after SEC acceptance, on the NYSE calendar in US
  Eastern time: before the open -> that day's open; during the session -> that day's close;
  at or after the close (13:00 on early-close days) or on a non-trading day -> the next
  session's open. Unknown acceptance counts as 16:00 ET on the filing date (flagged).
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from functools import cache
from typing import Literal

from signals.analytics.series import IssuerSeries
from signals.domain.calendars import (
    ET,
    is_trading_day,
    next_trading_day,
    session_open_close,
    to_et,
)

EntryKind = Literal["open", "close", "reported", "close_fallback"]

# How far a filed entry may step past a missing bar before giving up.
MAX_GAP_TRADING_DAYS = 5
UNKNOWN_ACCEPTANCE_TIME = time(16, 0)


@dataclass(frozen=True)
class Entry:
    date: date
    price_adj: float
    kind: EntryKind
    flags: tuple[str, ...] = ()


@cache
def _session(d: date) -> tuple[datetime, datetime]:
    return session_open_close(d)


def filed_target(
    accepted_at: datetime | None, filed_date: date
) -> tuple[date, Literal["open", "close"], tuple[str, ...]]:
    """The session and price point a follower could first trade at, before any bar check."""
    if accepted_at is None:
        at = datetime.combine(filed_date, UNKNOWN_ACCEPTANCE_TIME, ET)
        flags: tuple[str, ...] = ("acceptance_unknown",)
    else:
        at, flags = to_et(accepted_at), ()
    day = at.date()
    if is_trading_day(day):
        opened, closed = _session(day)
        if at < opened:
            return day, "open", flags
        if at < closed:
            return day, "close", flags
    return next_trading_day(day), "open", flags


def _positive(value: float | None) -> float | None:
    return value if value is not None and value > 0 else None


def filed_entry(
    accepted_at: datetime | None, filed_date: date, series: IssuerSeries
) -> Entry | None:
    day, kind, flags = filed_target(accepted_at, filed_date)
    price = _positive(series.open_adj(day) if kind == "open" else series.close_adj(day))
    if price is not None:
        return Entry(day, price, kind, flags)
    probe = day
    for _ in range(MAX_GAP_TRADING_DAYS):
        probe = next_trading_day(probe)
        price = _positive(series.open_adj(probe))
        if price is not None:
            return Entry(probe, price, "open", (*flags, "entry_gap"))
    return None


def executed_entry(trade_date: date, vwap: float | None, series: IssuerSeries) -> Entry | None:
    day = trade_date if is_trading_day(trade_date) else next_trading_day(trade_date)
    if vwap is not None and vwap > 0:
        factor = series.factor_on_or_before(trade_date)
        if factor is None and series.has(day):
            factor = series.factor_on_or_before(day)
        if factor is None:
            return None
        return Entry(day, vwap * factor, "reported")
    close = _positive(series.close_adj(day))
    if close is None:
        return None
    return Entry(day, close, "close_fallback", ("price_missing",))
