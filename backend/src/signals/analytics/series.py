"""Adjusted daily price series: per issuer (stitched across ticker changes) and per symbol.

Everything in analytics compares prices on the adjusted scale, `adjusted = raw x adj_factor`
with `adj_factor = adj_close / close` (spec 9.2). An issuer's series walks its dated ticker
intervals: each trading day takes the bar of the symbol valid that day, falling back to the
current symbol's bar (some providers map history onto the new symbol). A rename is not a
corporate action, so older segments are rescaled to join the newer ones without a jump.
"""

import bisect
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from signals.db.models import Ticker, TickerEvidence
from signals.domain.calendars import is_trading_day
from signals.domain.tickers import TickerInterval, ticker_intervals
from signals.domain.types import BENCHMARK_SYMBOLS
from signals.prices.base import get_bars

SERIES_COLUMNS = ("symbol", "open", "close", "adj_factor", "open_adj", "close_adj")

# symbol -> {date: (open, close, adj_close)}
_Bars = dict[str, dict[date, tuple[float, float, float]]]


def _num(value: float) -> float | None:
    return None if np.isnan(value) else float(value)


@dataclass
class IssuerSeries:
    """Daily bars on the adjusted scale. `frame` is indexed by trading dates (ascending) with
    columns symbol, open, close, adj_factor, open_adj, close_adj. Treat it as read-only: the
    lookups below are built from it once."""

    issuer_cik: int | None
    frame: pd.DataFrame

    def __post_init__(self) -> None:
        self._dates: list[date] = list(self.frame.index)
        self._pos: dict[date, int] = {d: i for i, d in enumerate(self._dates)}
        self._open_adj = self.frame["open_adj"].to_numpy(dtype=float, na_value=np.nan)
        self._close_adj = self.frame["close_adj"].to_numpy(dtype=float, na_value=np.nan)
        self._factor = self.frame["adj_factor"].to_numpy(dtype=float, na_value=np.nan)
        self._ordinals = np.array([d.toordinal() for d in self._dates], dtype=np.int64)

    @property
    def dates(self) -> list[date]:
        return self._dates

    def has(self, d: date) -> bool:
        return d in self._pos

    def open_adj(self, d: date) -> float | None:
        i = self._pos.get(d)
        return None if i is None else _num(self._open_adj[i])

    def close_adj(self, d: date) -> float | None:
        i = self._pos.get(d)
        return None if i is None else _num(self._close_adj[i])

    def factor_on_or_before(self, d: date) -> float | None:
        i = bisect.bisect_right(self._dates, d) - 1
        return None if i < 0 else _num(self._factor[i])

    def last_on_or_before(self, d: date) -> date | None:
        i = bisect.bisect_right(self._dates, d) - 1
        return None if i < 0 else self._dates[i]

    def first_on_or_after(self, d: date) -> date | None:
        i = bisect.bisect_left(self._dates, d)
        return None if i >= len(self._dates) else self._dates[i]

    def aligned(self, grid: np.ndarray, column: str = "close_adj") -> np.ndarray:
        """`column` ("close_adj" or "open_adj") on `grid` (ascending date ordinals); NaN
        where there is no bar."""
        values = self._open_adj if column == "open_adj" else self._close_adj
        out = np.full(len(grid), np.nan)
        if len(self._ordinals) == 0 or len(grid) == 0:
            return out
        idx = np.minimum(np.searchsorted(self._ordinals, grid), len(self._ordinals) - 1)
        hit = self._ordinals[idx] == grid
        out[hit] = values[idx[hit]]
        return out

    def first_date(self) -> date | None:
        return self._dates[0] if self._dates else None

    def last_date(self) -> date | None:
        return self._dates[-1] if self._dates else None


@dataclass
class BenchPanel:
    """Benchmark series by symbol (SPY, QQQ, the sector ETFs); symbols without bars are absent."""

    series: dict[str, IssuerSeries]

    def get(self, symbol: str | None) -> IssuerSeries | None:
        return None if symbol is None else self.series.get(symbol)


def _empty_frame() -> pd.DataFrame:
    frame = pd.DataFrame({c: [] for c in SERIES_COLUMNS}, index=pd.Index([], dtype=object))
    frame.index.name = "date"
    return frame


def _build_frame(rows: Sequence[tuple[date, str, float, float, float]]) -> pd.DataFrame:
    """rows: (date, symbol, open, close, adj_factor), dates ascending."""
    if not rows:
        return _empty_frame()
    dates, symbols, opens, closes, factors = zip(*rows, strict=True)
    open_arr = np.asarray(opens, dtype=float)
    close_arr = np.asarray(closes, dtype=float)
    factor_arr = np.asarray(factors, dtype=float)
    frame = pd.DataFrame(
        {
            "symbol": list(symbols),
            "open": open_arr,
            "close": close_arr,
            "adj_factor": factor_arr,
            "open_adj": open_arr * factor_arr,
            "close_adj": close_arr * factor_arr,
        },
        index=pd.Index(list(dates), dtype=object, name="date"),
    )
    return frame


def _bars_by_symbol(frame: pd.DataFrame) -> _Bars:
    bars: _Bars = {}
    for sym, d, opened, close, adj_close in frame[
        ["symbol", "date", "open", "close", "adj_close"]
    ].itertuples(index=False, name=None):
        if close is None or not close > 0 or adj_close is None or np.isnan(adj_close):
            continue  # an unusable bar is treated as missing; nothing is made up
        if not is_trading_day(d):
            continue
        opened = float(opened) if opened is not None and not np.isnan(opened) else np.nan
        bars.setdefault(str(sym), {})[d] = (opened, float(close), float(adj_close))
    return bars


def load_symbol_series(session: Session, symbol: str, start: date, end: date) -> IssuerSeries:
    bars = _bars_by_symbol(get_bars(session, [symbol], start, end)).get(symbol, {})
    rows = [(d, symbol, o, c, a / c) for d, (o, c, a) in sorted(bars.items())]
    return IssuerSeries(None, _build_frame(rows))


def load_bench(session: Session, start: date, end: date) -> BenchPanel:
    by_symbol = _bars_by_symbol(get_bars(session, list(BENCHMARK_SYMBOLS), start, end))
    series = {
        sym: IssuerSeries(
            None, _build_frame([(d, sym, o, c, a / c) for d, (o, c, a) in sorted(bars.items())])
        )
        for sym, bars in by_symbol.items()
        if bars
    }
    return BenchPanel(series)


# ----------------------------------------------------------------------------- issuer series
@dataclass(frozen=True)
class _Claim:
    issuer_cik: int
    valid_from: date
    valid_to: date | None
    min_seen: date | None


def _owner_on(claims: Iterable[_Claim], d: date) -> int | None:
    """Which issuer owns a symbol on `d`: the same rule as `tickers.issuer_for_symbol`."""
    covering = [c for c in claims if c.valid_from <= d and (c.valid_to is None or d <= c.valid_to)]
    if not covering:
        return None
    seen = [c for c in covering if c.min_seen is not None and c.min_seen <= d]
    if seen:
        return max(seen, key=lambda c: c.min_seen or d).issuer_cik
    later = [c for c in covering if c.min_seen is not None]
    if later:
        return min(later, key=lambda c: c.min_seen or d).issuer_cik
    return covering[0].issuer_cik


def _contested_claims(
    session: Session, issuer_cik: int, symbols: Sequence[str]
) -> dict[str, list[_Claim]]:
    """Every issuer's claim on the symbols that another issuer also used (reused tickers)."""
    shared = set(
        session.scalars(
            select(Ticker.symbol).where(
                Ticker.symbol.in_(list(symbols)), Ticker.issuer_cik != issuer_cik
            )
        )
    )
    if not shared:
        return {}
    rows = session.execute(
        select(
            Ticker.symbol,
            Ticker.issuer_cik,
            Ticker.valid_from,
            Ticker.valid_to,
            TickerEvidence.min_seen,
        )
        .join(
            TickerEvidence,
            (TickerEvidence.issuer_cik == Ticker.issuer_cik)
            & (TickerEvidence.symbol == Ticker.symbol),
            isouter=True,
        )
        .where(Ticker.symbol.in_(sorted(shared)))
    ).all()
    claims: dict[str, list[_Claim]] = {}
    for r in rows:
        claims.setdefault(r.symbol, []).append(
            _Claim(r.issuer_cik, r.valid_from, r.valid_to, r.min_seen)
        )
    return claims


def _interval_on(intervals: Sequence[TickerInterval], d: date) -> str | None:
    symbol = None
    for iv in intervals:  # ordered by valid_from; the latest start covering `d` wins
        if iv.valid_from <= d and (iv.valid_to is None or d <= iv.valid_to):
            symbol = iv.symbol
    return symbol


def _current(intervals: Sequence[TickerInterval]) -> str:
    open_ended = [iv for iv in intervals if iv.valid_to is None]
    if open_ended:
        return open_ended[-1].symbol
    return max(intervals, key=lambda iv: (iv.valid_to or iv.valid_from, iv.valid_from)).symbol


def load_issuer_series(session: Session, issuer_cik: int, start: date, end: date) -> IssuerSeries:
    intervals = ticker_intervals(session, issuer_cik)
    if not intervals:
        return IssuerSeries(issuer_cik, _empty_frame())
    current = _current(intervals)
    symbols = sorted({iv.symbol for iv in intervals})
    bars = _bars_by_symbol(get_bars(session, symbols, start, end))
    claims = _contested_claims(session, issuer_cik, symbols)

    def usable(symbol: str, d: date) -> bool:
        if d not in bars.get(symbol, {}):
            return False
        if symbol not in claims:
            return True
        owner = _owner_on(claims[symbol], d)
        return owner is None or owner == issuer_cik

    chosen: list[tuple[date, str]] = []
    for d in sorted({d for per_symbol in bars.values() for d in per_symbol}):
        symbol = _interval_on(intervals, d)
        if symbol is not None and usable(symbol, d):
            chosen.append((d, symbol))
        elif usable(current, d):
            chosen.append((d, current))
    if not chosen:
        return IssuerSeries(issuer_cik, _empty_frame())

    raw = [bars[s][d] for d, s in chosen]
    factors = [a / c for _, c, a in raw]
    multipliers = _stitch_multipliers(chosen, raw, factors, bars, usable)
    rows = [
        (d, s, o, c, f * m)
        for (d, s), (o, c, _), f, m in zip(chosen, raw, factors, multipliers, strict=True)
    ]
    return IssuerSeries(issuer_cik, _build_frame(rows))


def _stitch_multipliers(
    chosen: Sequence[tuple[date, str]],
    raw: Sequence[tuple[float, float, float]],
    factors: Sequence[float],
    bars: _Bars,
    usable: Callable[[str, date], bool],
) -> list[float]:
    """Per-row factor multipliers that join each symbol segment to the newer one.

    Walking boundaries from newest to oldest, the older segment is scaled so its adjusted
    close meets the newer segment's: through the newer symbol's own bar on the older
    segment's last day when the provider has one (that captures a split taking effect with
    the new symbol), otherwise by making `adj_factor` continuous (a rename is not a
    corporate action).
    """
    n = len(chosen)
    starts = [i for i in range(n) if i == 0 or chosen[i][1] != chosen[i - 1][1]]
    multipliers = [1.0] * n
    for k in range(len(starts) - 2, -1, -1):
        a_first, b_first = starts[k], starts[k + 1]
        a_last = b_first - 1
        last_day, b_symbol = chosen[a_last][0], chosen[b_first][1]
        m_b = multipliers[b_first]
        adj_a_last = raw[a_last][2]
        if usable(b_symbol, last_day):
            m_a = bars[b_symbol][last_day][2] * m_b / adj_a_last
        else:
            m_a = factors[b_first] * m_b / factors[a_last]
        for i in range(a_first, a_last + 1):
            multipliers[i] = m_a
    return multipliers
