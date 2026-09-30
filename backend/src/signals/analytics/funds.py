"""Fund copycat portfolio (spec 9.5): a tracked fund's reported 13F holdings, bought and
held from the start of each period until the next period starts.

- Holdings: the period's effective share positions (put_call '', amendments applied, rows
  for the same CUSIP summed), weighted by reported value. A position counts only when its
  CUSIP maps to a ticker (`securities.ticker`) with a price during the period; the rest are
  left out, the weights renormalized, and `coverage` is the priced share of the value. Put
  and call rows are never holdings.
- Start: executed basis -> the close of the quarter-end date (or the last trading day
  before it); filed basis -> the spec 9.2 entry after the period's first 13F acceptance
  (that session's open or close, on SPY's bars).
- A period that starts at or after a later period's start (a late report filed with or
  after the next one) is never held: the follower already has newer holdings. A period
  without any priced holding is skipped, so the previous holdings carry on.
- Within a period: nav(t) = nav(start) x sum_i w_i P_i(t) / P_i(start), with P the adjusted
  close (the adjusted open at an open start; at an open rebalance the old holdings are sold
  at that open). A holding whose prices stop carries its last price; one first priced after
  the start is flat until then.
- `sector` holds the same weights in each holding's sector ETF (SPY when the issuer has no
  sector or the ETF has no price at the start); `spy` and `qqq` are bought and held from the
  first row; `coverage` is the coverage of the holdings in force at the end of each day.
"""

import bisect
import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

import numpy as np
import pandas as pd
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from signals.analytics.copycat import benchmark_daily
from signals.analytics.decisions import effective_acceptance
from signals.analytics.entries import filed_entry
from signals.analytics.returns import sector_etf_for
from signals.analytics.series import (
    BenchPanel,
    IssuerSeries,
    _bars_by_symbol,
    _build_frame,
    load_symbol_series,
)
from signals.db.models import FundFiling, FundPosition, Issuer, Security
from signals.domain.calendars import is_trading_day, prev_trading_day, trading_days
from signals.domain.tickers import canonical_symbol
from signals.domain.types import Basis
from signals.prices.base import get_bars

StartKind = Literal["open", "close"]
NAV_COLUMNS = ["nav", "spy", "qqq", "sector", "coverage"]
# Prices load from a few days before the first quarter end (its executed start may be earlier).
PRICE_LOOKBACK_DAYS = 7


@dataclass(frozen=True)
class FundPeriodHoldings:
    period: date
    start: date
    start_kind: StartKind
    weights: dict[str, float]  # canonical symbol -> weight among priced share positions (sum 1)
    coverage: float  # priced value / total share-position value


@dataclass(frozen=True)
class PeriodBook:
    """One period's reported share positions and first disclosure, before prices."""

    period: date
    values: dict[str, float]  # symbol -> reported value of the positions mapped to it
    total: float  # reported value of every share position, mapped or not
    accepted_at: datetime | None  # the period's first 13F acceptance (None when unknown)
    filed_date: date


@dataclass(frozen=True)
class FundInputs:
    books: list[PeriodBook]
    panel: dict[str, IssuerSeries]  # symbol -> adjusted series
    sector_etfs: dict[str, str | None]  # symbol -> its issuer's sector ETF
    spy: IssuerSeries | None


def _moment(day: date, kind: str) -> tuple[date, int]:
    """Order of starts within the calendar: a session's open comes before its close."""
    return day, 0 if kind == "open" else 1


# ----------------------------------------------------------------------------- loading
def load_fund_inputs(session: Session, filer_cik: int, *, end: date | None = None) -> FundInputs:
    """Holdings, prices and sectors for one filer. With `end`, filings made after it are
    unknown and prices stop there."""
    last = end or date.max
    filings = session.execute(
        select(FundFiling.period_of_report, FundFiling.accepted_at, FundFiling.filed_date).where(
            FundFiling.filer_cik == filer_cik,
            FundFiling.filed_date <= last,
            or_(
                FundFiling.submission_type.is_(None),
                FundFiling.submission_type.not_like("13F-NT%"),
            ),
        )
    ).all()
    first_public: dict[date, tuple[datetime, datetime | None, date]] = {}
    for period, accepted_at, filed_date in filings:
        when = effective_acceptance(accepted_at, filed_date)
        if period not in first_public or when < first_public[period][0]:
            first_public[period] = (when, accepted_at, filed_date)
    if not first_public:
        return FundInputs([], {}, {}, None)

    positions = session.execute(
        select(
            FundPosition.period,
            func.sum(FundPosition.value_usd),
            Security.ticker,
            Security.issuer_cik,
        )
        .join(Security, Security.cusip == FundPosition.cusip, isouter=True)
        .where(
            FundPosition.filer_cik == filer_cik,
            FundPosition.is_effective.is_(True),
            FundPosition.put_call == "",
            FundPosition.period.in_(list(first_public)),
        )
        .group_by(FundPosition.period, FundPosition.cusip, Security.ticker, Security.issuer_cik)
    ).all()
    values: dict[date, dict[str, float]] = {}
    totals: dict[date, float] = {}
    issuer_of: dict[str, int] = {}
    for period, value, ticker, issuer_cik in positions:
        if value is None or not value > 0:
            continue
        totals[period] = totals.get(period, 0.0) + float(value)
        symbol = canonical_symbol(ticker)
        if symbol is None:
            continue
        book = values.setdefault(period, {})
        book[symbol] = book.get(symbol, 0.0) + float(value)
        if issuer_cik is not None:
            issuer_of.setdefault(symbol, int(issuer_cik))
    books = [
        PeriodBook(period, values.get(period, {}), totals[period], accepted_at, filed_date)
        for period, (_, accepted_at, filed_date) in sorted(first_public.items())
        if totals.get(period, 0.0) > 0
    ]
    if not books:
        return FundInputs([], {}, {}, None)

    start = books[0].period - timedelta(days=PRICE_LOOKBACK_DAYS)
    symbols = sorted({s for b in books for s in b.values})
    bars = _bars_by_symbol(get_bars(session, symbols, start, last)) if symbols else {}
    panel = {
        symbol: IssuerSeries(
            None, _build_frame([(d, symbol, o, c, a / c) for d, (o, c, a) in sorted(per.items())])
        )
        for symbol, per in bars.items()
        if per
    }
    sectors: dict[int, str | None] = {}
    if issuer_of:
        rows = session.execute(
            select(Issuer.cik, Issuer.sector).where(Issuer.cik.in_(set(issuer_of.values())))
        )
        sectors = {cik: sector for cik, sector in rows}
    sector_etfs = {symbol: sector_etf_for(sectors.get(cik)) for symbol, cik in issuer_of.items()}
    spy = load_symbol_series(session, "SPY", start, last)
    return FundInputs(books, panel, sector_etfs, spy)


def _priced_between(series: IssuerSeries | None, first: date, last: date) -> bool:
    if series is None:
        return False
    bar = series.first_on_or_after(first)
    return bar is not None and bar <= last


def fund_periods(inputs: FundInputs, basis: Basis | str) -> list[FundPeriodHoldings]:
    """The periods a follower holds on `basis`, in order (see the module docstring)."""
    basis = Basis(basis)
    starts: list[tuple[PeriodBook, date, StartKind]] = []
    for book in inputs.books:
        if basis is Basis.EXECUTED:
            day = book.period if is_trading_day(book.period) else prev_trading_day(book.period)
            starts.append((book, day, "close"))
            continue
        entry = (
            filed_entry(book.accepted_at, book.filed_date, inputs.spy)
            if inputs.spy is not None
            else None
        )
        if entry is not None:
            starts.append((book, entry.date, "open" if entry.kind == "open" else "close"))

    held: list[tuple[PeriodBook, date, StartKind]] = []
    earliest_later: tuple[date, int] | None = None
    for book, day, kind in sorted(starts, key=lambda s: s[0].period, reverse=True):
        if earliest_later is None or _moment(day, kind) < earliest_later:
            held.append((book, day, kind))
            earliest_later = _moment(day, kind)
    held.reverse()

    periods: list[FundPeriodHoldings] = []
    for k, (book, day, kind) in enumerate(held):
        until = held[k + 1][1] if k + 1 < len(held) else date.max
        priced = {
            symbol: value
            for symbol, value in book.values.items()
            if _priced_between(inputs.panel.get(symbol), day, until)
        }
        priced_value = sum(priced.values())
        if not priced_value > 0:
            continue
        periods.append(
            FundPeriodHoldings(
                period=book.period,
                start=day,
                start_kind=kind,
                weights={symbol: value / priced_value for symbol, value in priced.items()},
                coverage=min(1.0, priced_value / book.total),
            )
        )
    return periods


def load_fund_periods(
    session: Session, filer_cik: int, *, basis: Basis | str
) -> tuple[list[FundPeriodHoldings], dict[str, IssuerSeries]]:
    inputs = load_fund_inputs(session, filer_cik)
    return fund_periods(inputs, basis), inputs.panel


# ----------------------------------------------------------------------------- the curve
def empty_fund_nav() -> pd.DataFrame:
    return pd.DataFrame(
        {c: pd.Series([], dtype=float) for c in NAV_COLUMNS}, index=pd.Index([], dtype=object)
    )


def _price(series: IssuerSeries | None, day: date, kind: str) -> float:
    if series is None:
        return math.nan
    value = series.open_adj(day) if kind == "open" else series.close_adj(day)
    return value if value is not None and value > 0 else math.nan


def _relative_path(
    series: IssuerSeries | None,
    start: date,
    kind: StartKind,
    marks: np.ndarray,
    sell_at_open: date | None,
) -> np.ndarray | None:
    """Value of one unit bought at the start: at the start, at each close in `marks`, then
    at the open of `sell_at_open`. None when there is no price at all."""
    if series is None:
        return None
    tail = [_price(series, sell_at_open, "open")] if sell_at_open is not None else []
    points = np.concatenate(([_price(series, start, kind)], series.aligned(marks), tail))
    filled = pd.Series(points, dtype=float).ffill().bfill().to_numpy()
    if not filled[0] > 0:
        return None
    return filled / filled[0]


def _basket_path(
    legs: Sequence[tuple[float, IssuerSeries | None]],
    start: date,
    kind: StartKind,
    marks: np.ndarray,
    sell_at_open: date | None,
) -> np.ndarray:
    """Buy-and-hold value of the weighted legs (a leg without prices is held as cash)."""
    total = np.zeros(1 + len(marks) + (sell_at_open is not None))
    for weight, series in legs:
        path = _relative_path(series, start, kind, marks, sell_at_open)
        total += weight * (path if path is not None else 1.0)
    return total


def _sector_legs(
    weights: Mapping[str, float],
    sector_etfs: Mapping[str, str | None],
    bench: BenchPanel,
    start: date,
    kind: StartKind,
) -> list[tuple[float, IssuerSeries | None]]:
    by_etf: dict[str, float] = {}
    for symbol, weight in weights.items():
        etf = sector_etfs.get(symbol)
        if etf is None or math.isnan(_price(bench.get(etf), start, kind)):
            etf = "SPY"
        by_etf[etf] = by_etf.get(etf, 0.0) + weight
    return [(weight, bench.get(etf)) for etf, weight in by_etf.items()]


def _buy_and_hold(series: IssuerSeries | None, grid: np.ndarray) -> np.ndarray:
    if series is None:
        return np.full(len(grid), np.nan)
    return np.cumprod(1.0 + benchmark_daily(series, grid))


def _row(rows: Mapping[date, int], day: date) -> int:
    if day not in rows:
        raise ValueError(f"period start {day} is not a trading day")
    return rows[day]


def fund_copycat_nav(
    periods: Sequence[FundPeriodHoldings],
    panel: Mapping[str, IssuerSeries],
    bench: BenchPanel,
    *,
    end: date,
    sector_etfs: Mapping[str, str | None] | None = None,
) -> pd.DataFrame:
    """Daily frame (nav, spy, qqq, sector, coverage) from the first period's start to `end`,
    1.0 on the first row: the start's close, or the session before an open start. Periods
    starting after `end` are ignored."""
    ordered = sorted(
        (p for p in periods if p.start <= end), key=lambda p: _moment(p.start, p.start_kind)
    )
    if not ordered:
        return empty_fund_nav()
    first = ordered[0]
    origin = first.start if first.start_kind == "close" else prev_trading_day(first.start)
    dates = trading_days(origin, end)
    rows = {d: i for i, d in enumerate(dates)}
    grid = np.array([d.toordinal() for d in dates], dtype=np.int64)
    n = len(dates)
    etfs = sector_etfs or {}
    nav, sector = np.ones(n), np.ones(n)
    coverage = np.full(n, float(first.coverage))
    level = sector_level = 1.0
    for k, p in enumerate(ordered):
        start_row = _row(rows, p.start)
        first_row = start_row if p.start_kind == "open" else start_row + 1
        last_row, sell_at_open = n - 1, None
        if k + 1 < len(ordered):
            nxt = ordered[k + 1]
            next_row = _row(rows, nxt.start)
            if nxt.start_kind == "open":
                last_row, sell_at_open = next_row - 1, nxt.start
            else:
                last_row = next_row
        marks = grid[first_row : last_row + 1]
        held = _basket_path(
            [(w, panel.get(symbol)) for symbol, w in p.weights.items()],
            p.start,
            p.start_kind,
            marks,
            sell_at_open,
        )
        in_sector = _basket_path(
            _sector_legs(p.weights, etfs, bench, p.start, p.start_kind),
            p.start,
            p.start_kind,
            marks,
            sell_at_open,
        )
        days = slice(first_row, last_row + 1)
        nav[days] = level * held[1 : 1 + len(marks)]
        sector[days] = sector_level * in_sector[1 : 1 + len(marks)]
        coverage[start_row:] = p.coverage
        level *= held[-1]
        sector_level *= in_sector[-1]
    return pd.DataFrame(
        {
            "nav": nav,
            "spy": _buy_and_hold(bench.get("SPY"), grid),
            "qqq": _buy_and_hold(bench.get("QQQ"), grid),
            "sector": sector,
            "coverage": coverage,
        },
        index=pd.Index(dates, dtype=object),
    )


def fund_quarterly_excess(nav: pd.DataFrame, starts: Sequence[date]) -> list[float]:
    """Each complete holding period's return minus SPY's over the same rows (from one start
    to the next); a period whose next start is beyond the data is not complete yet."""
    if nav.empty:
        return []
    dates: list[date] = list(nav.index)
    values = nav["nav"].to_numpy(dtype=float)
    spy = nav["spy"].to_numpy(dtype=float)
    at = [bisect.bisect_right(dates, d) - 1 if d <= dates[-1] else -1 for d in sorted(starts)]
    excess: list[float] = []
    for i, j in itertools.pairwise(at):
        if i < 0 or j <= i:
            continue
        value = values[j] / values[i] - spy[j] / spy[i]
        if math.isfinite(value):
            excess.append(float(value))
    return excess
