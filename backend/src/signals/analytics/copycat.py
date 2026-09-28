"""Insider copycat portfolio (spec 9.4): the calendar-time portfolio of research practice.

Each buy decision opens a lot of weight 1 at its entry (spec 9.2). A discretionary sale by
the same owner in the same issuer scales every open lot of that issuer by (1 - fraction
sold) at the sale's own entry. A lot closes after `hold_days` trading days, when its weight
falls under `min_weight`, or when its prices stop (realized at the last close). Each day

    r = (sum w_i r_i + max(0, 1 - sum w) r_SPY) / max(1, sum w)

so at least one full position is always invested, money freed by sales sits in SPY, and
with no open lots the portfolio earns SPY. The `sector` column is the same portfolio with
each stock swapped for its sector ETF (SPY when there is none or it has no data yet).

Timing within a day: lots and sales with an "open" entry act at the start of their day (so
the lot earns that day's open-to-close move); every other entry kind acts at its day's end.
Weights are fixed per lot (daily rebalanced), not drifted by performance.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from signals.analytics.entries import Entry
from signals.analytics.series import BenchPanel, IssuerSeries
from signals.domain.calendars import trading_days

NAV_COLUMNS = ["nav", "spy", "qqq", "sector", "invested"]
HOLD_DAYS = 252
MIN_WEIGHT = 0.05


@dataclass(frozen=True)
class Lot:
    lot_id: int
    issuer_cik: int
    series: IssuerSeries
    entry: Entry
    sector_etf: str | None


@dataclass(frozen=True)
class SaleEvent:
    issuer_cik: int
    entry: Entry
    fraction: float


def empty_nav() -> pd.DataFrame:
    return pd.DataFrame(
        {c: pd.Series([], dtype=float) for c in NAV_COLUMNS}, index=pd.Index([], dtype=object)
    )


def _moment(day: int, kind: str) -> int:
    """Event order on the grid: the start of day i is 2i, its end 2i + 1."""
    return 2 * day + (0 if kind == "open" else 1)


def _chain_returns(base: float, closes: np.ndarray) -> np.ndarray:
    """Daily returns of a position bought at `base` and marked at `closes` (NaN = no bar,
    the last price carries). NaN until the first known price."""
    prices = pd.Series(np.concatenate(([base], closes))).ffill().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        return prices[1:] / prices[:-1] - 1.0


def benchmark_daily(series: IssuerSeries | None, grid: np.ndarray) -> np.ndarray:
    """Close-to-close daily returns on the grid; 0 on the first day and where undefined."""
    if series is None or len(grid) == 0:
        return np.zeros(len(grid))
    closes = series.aligned(grid)
    returns = np.zeros(len(grid))
    if len(grid) > 1:
        chained = _chain_returns(closes[0], closes[1:])
        returns[1:] = np.nan_to_num(chained, nan=0.0, posinf=0.0, neginf=0.0)
    return returns


def _lot_weights(
    lot_add: int,
    first: int,
    last: int,
    sales: Sequence[tuple[int, float]],
    min_weight: float,
) -> tuple[np.ndarray, int]:
    """Weights on return days first..last and the (possibly earlier) last day."""
    weights = np.ones(last - first + 1)
    w = 1.0
    for moment, fraction in sales:
        if moment < lot_add:
            continue
        if moment > 2 * last + 1:
            break
        w *= 1.0 - min(max(fraction, 0.0), 1.0)
        effective = (
            moment + 1
        ) // 2  # a start-of-day sale counts that day, an end-of-day one the next
        weights[max(effective - first, 0) :] = w
        if w < min_weight:
            last = min(last, moment // 2)
            break
    return weights[: max(last - first + 1, 0)], last


def copycat_nav(
    lots: Sequence[Lot],
    sales: Sequence[SaleEvent],
    bench: BenchPanel,
    start: date,
    end: date,
    *,
    hold_days: int = HOLD_DAYS,
    min_weight: float = MIN_WEIGHT,
) -> pd.DataFrame:
    """Daily frame over trading days start..end: nav, spy, qqq, sector (1.0 on the first
    day) and invested (the total lot weight earning that day)."""
    dates = trading_days(start, end)
    if not dates:
        return empty_nav()
    n = len(dates)
    grid = np.array([d.toordinal() for d in dates], dtype=np.int64)
    position = {d: i for i, d in enumerate(dates)}
    spy, qqq = bench.get("SPY"), bench.get("QQQ")
    r_spy, r_qqq = benchmark_daily(spy, grid), benchmark_daily(qqq, grid)

    sales_by_issuer: dict[int, list[tuple[int, float]]] = {}
    for sale in sales:
        day = position.get(sale.entry.date)
        if day is not None:
            sales_by_issuer.setdefault(sale.issuer_cik, []).append(
                (_moment(day, sale.entry.kind), sale.fraction)
            )
    for events in sales_by_issuer.values():
        events.sort(key=lambda e: e[0])

    weight_sum, stock_sum, sector_sum = np.zeros(n), np.zeros(n), np.zeros(n)
    for lot in lots:
        added = position.get(lot.entry.date)
        last_bar = lot.series.last_date()
        if added is None or last_bar is None or not lot.entry.price_adj > 0:
            continue
        is_open = lot.entry.kind == "open"
        # an open-entry lot on the very first day folds that day's move into the next one
        first = max(added if is_open else added + 1, 1)
        last_priced = int(np.searchsorted(grid, last_bar.toordinal(), side="right")) - 1
        last = min(n - 1, added + hold_days, last_priced)
        if last < first:
            continue
        weights, last = _lot_weights(
            _moment(added, lot.entry.kind),
            first,
            last,
            sales_by_issuer.get(lot.issuer_cik, []),
            min_weight,
        )
        if last < first:
            continue
        days = slice(first, last + 1)
        stock = _chain_returns(lot.entry.price_adj, lot.series.aligned(grid)[days])
        etf = bench.get(lot.sector_etf)
        if etf is None:
            sector = r_spy[days]
        else:
            base = etf.open_adj(lot.entry.date) if is_open else etf.close_adj(lot.entry.date)
            sector = _chain_returns(np.nan if base is None else base, etf.aligned(grid)[days])
            sector = np.where(np.isfinite(sector), sector, r_spy[days])
        weight_sum[days] += weights
        stock_sum[days] += weights * stock
        sector_sum[days] += weights * sector

    denominator = np.maximum(1.0, weight_sum)
    in_spy = np.maximum(0.0, 1.0 - weight_sum) * r_spy
    r_nav = (stock_sum + in_spy) / denominator
    r_sector = (sector_sum + in_spy) / denominator
    r_nav[0] = r_sector[0] = 0.0
    frame = pd.DataFrame(
        {
            "nav": np.cumprod(1.0 + r_nav),
            "spy": np.cumprod(1.0 + r_spy) if spy is not None else np.full(n, np.nan),
            "qqq": np.cumprod(1.0 + r_qqq) if qqq is not None else np.full(n, np.nan),
            "sector": np.cumprod(1.0 + r_sector),
            "invested": weight_sum,
        },
        index=pd.Index(dates, dtype=object),
    )
    return frame
