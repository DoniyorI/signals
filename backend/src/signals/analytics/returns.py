"""Per-decision returns (spec 9.3): 1/3/6/12-month horizons, excess returns and lag cost.

Horizons exit at the adjusted close 21/63/126/252 trading days after the entry. Excess is
the raw return minus the benchmark's over the same entry-to-exit dates; sales are scored
with the sign flipped (a sale is right when the stock then lags). A horizon is complete once
market data (SPY) reaches its exit day; a stock whose prices stop before that exits at its
last close (`last_price`), since it was most likely delisted.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from signals.analytics.entries import Entry, executed_entry, filed_entry
from signals.analytics.series import BenchPanel, IssuerSeries, load_bench, load_issuer_series
from signals.db.models import Decision, DecisionReturn, Issuer
from signals.domain.calendars import add_trading_days
from signals.domain.types import HORIZON_TRADING_DAYS, SECTOR_ETF, Basis, Horizon, Sector

Direction = Literal["buy", "sell"]
ExitReason = Literal["horizon", "last_price"]

# Price history loaded before a decision's first trade (for adj_factor lookups).
LOOKBACK_DAYS = 45


@dataclass(frozen=True)
class HorizonResult:
    horizon: Horizon
    exit_date: date
    raw: float
    excess_spy: float | None
    excess_qqq: float | None
    excess_sector: float | None
    complete: bool
    exit_reason: ExitReason
    flags: tuple[str, ...] = ()


def sector_etf_for(sector: str | None) -> str | None:
    try:
        return SECTOR_ETF.get(Sector(sector)) if sector else None
    except ValueError:
        return None


def benchmark_return(bench: IssuerSeries | None, entry: Entry, exit_date: date) -> float | None:
    """The benchmark bought when the follower buys (the open for open entries, else the
    close of the entry day) and sold at the exit day's close."""
    if bench is None:
        return None
    start = bench.open_adj(entry.date) if entry.kind == "open" else bench.close_adj(entry.date)
    end = bench.close_adj(exit_date)
    if start is None or end is None or start <= 0:
        return None
    return end / start - 1


def horizon_returns(
    entry: Entry,
    direction: Direction,
    series: IssuerSeries,
    bench: BenchPanel,
    sector_etf: str | None,
    as_of: date,
) -> list[HorizonResult]:
    if entry.date > as_of or entry.price_adj <= 0:
        return []
    spy = bench.get("SPY")
    spy_last = spy.last_date() if spy is not None else None
    frontier = min(as_of, spy_last) if spy_last is not None else as_of
    last = series.last_date()
    sign = 1.0 if direction == "buy" else -1.0
    results: list[HorizonResult] = []
    for horizon, n in HORIZON_TRADING_DAYS.items():
        target = add_trading_days(entry.date, n)
        flags: tuple[str, ...] = ()
        reason: ExitReason = "horizon"
        if target > frontier:
            exit_date, complete = series.last_on_or_before(as_of), False
        elif last is None or last < target:
            exit_date, complete, reason, flags = last, True, "last_price", ("prices_ended",)
        elif series.has(target):
            exit_date, complete = target, True
        else:
            exit_date, complete, flags = series.last_on_or_before(target), True, ("exit_gap",)
        if exit_date is None or exit_date < entry.date:
            continue
        close = series.close_adj(exit_date)
        if close is None:
            continue
        stock = close / entry.price_adj - 1

        def excess(
            symbol: str | None, exit_on: date = exit_date, ret: float = stock
        ) -> float | None:
            bench_ret = benchmark_return(bench.get(symbol), entry, exit_on)
            return None if bench_ret is None else sign * (ret - bench_ret)

        results.append(
            HorizonResult(
                horizon=horizon,
                exit_date=exit_date,
                raw=sign * stock,
                excess_spy=excess("SPY"),
                excess_qqq=excess("QQQ"),
                excess_sector=excess(sector_etf),
                complete=complete,
                exit_reason=reason,
                flags=flags,
            )
        )
    return results


def lag_cost(direction: Direction, filed: Entry | None, executed: Entry | None) -> float | None:
    """How much of the move was gone before the public could act (sign flipped for sales)."""
    if filed is None or executed is None or executed.price_adj <= 0:
        return None
    move = filed.price_adj / executed.price_adj - 1
    return move if direction == "buy" else -move


def decision_entries(decision: Any, series: IssuerSeries) -> tuple[Entry | None, Entry | None]:
    """(filed, executed) entries for a decision row with accepted_at, filed_date,
    first_trade_date and vwap."""
    filed = None
    if decision.filed_date is not None or decision.accepted_at is not None:
        filed_date = decision.filed_date or decision.accepted_at.date()
        filed = filed_entry(decision.accepted_at, filed_date, series)
    executed = executed_entry(decision.first_trade_date, decision.vwap, series)
    return filed, executed


def compute_decision_returns(
    session: Session, *, decision_ids: Collection[int] | None = None, as_of: date
) -> int:
    """Replace `decision_returns` rows (both bases, 4 horizons) and `decisions.lag_cost` for
    the decisions (or all). Returns the number of rows written. A basis without an entry
    price writes no rows, which is how coverage counts decisions without prices."""
    query = select(
        Decision.id,
        Decision.issuer_cik,
        Decision.direction,
        Decision.first_trade_date,
        Decision.vwap,
        Decision.accepted_at,
        Decision.filed_date,
    ).order_by(Decision.issuer_cik, Decision.id)
    scope = delete(DecisionReturn)
    if decision_ids is not None:
        ids = list(decision_ids)
        query = query.where(Decision.id.in_(ids))
        scope = scope.where(DecisionReturn.decision_id.in_(ids))
    session.execute(scope)
    decisions = session.execute(query).all()
    if not decisions:
        return 0

    by_issuer: dict[int, list[Any]] = {}
    for d in decisions:
        by_issuer.setdefault(d.issuer_cik, []).append(d)
    sectors: dict[int, str | None] = {
        cik: sector
        for cik, sector in session.execute(
            select(Issuer.cik, Issuer.sector).where(Issuer.cik.in_(list(by_issuer)))
        )
    }
    earliest = min(d.first_trade_date for d in decisions) - timedelta(days=LOOKBACK_DAYS)
    bench = load_bench(session, earliest, as_of)

    rows: list[dict[str, Any]] = []
    lag_costs: list[dict[str, Any]] = []
    for issuer_cik, group in by_issuer.items():
        start = min(d.first_trade_date for d in group) - timedelta(days=LOOKBACK_DAYS)
        series = load_issuer_series(session, issuer_cik, start, as_of)
        sector_etf = sector_etf_for(sectors.get(issuer_cik))
        for d in group:
            filed, executed = decision_entries(d, series)
            lag_costs.append({"id": d.id, "lag_cost": lag_cost(d.direction, filed, executed)})
            for basis, entry in ((Basis.FILED, filed), (Basis.EXECUTED, executed)):
                if entry is None:
                    continue
                for r in horizon_returns(entry, d.direction, series, bench, sector_etf, as_of):
                    rows.append(
                        {
                            "decision_id": d.id,
                            "basis": basis.value,
                            "horizon": r.horizon.value,
                            "entry_date": entry.date,
                            "entry_price_adj": entry.price_adj,
                            "entry_kind": entry.kind,
                            "exit_date": r.exit_date,
                            "raw_return": r.raw,
                            "excess_spy": r.excess_spy,
                            "excess_qqq": r.excess_qqq,
                            "excess_sector": r.excess_sector,
                            "is_complete": r.complete,
                            "exit_reason": r.exit_reason,
                            "flags": [*entry.flags, *r.flags],
                        }
                    )
    if rows:
        session.execute(insert(DecisionReturn), rows)
    session.execute(update(Decision), lag_costs)
    return len(rows)
