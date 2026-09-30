"""Profile stats and reliability ratings (spec 9.6).

Computed per insider (over the decisions they are an owner of) and per tracked fund, on both
bases; insider rows also per `include_10b5_1` toggle (off: pre-planned decisions are left out
of everything, including the population mean).

- Summary: decisions, buys, sells and complete decisions (6m horizon complete, with an SPY
  excess); over the complete ones, the mean, median and raw mean 6m return, the hit rate
  (share with positive excess) and the best and worst decision; the average disclosure lag
  and lag cost over all of them.
- Windows and risk: the insider copycat (spec 9.4) built from the owner's buy lots and sales
  at their entries on that basis (from `decision_returns`), or the fund copycat (spec 9.5).
  The risk label comes from the 5y volatility, else the full history's.
- Reliability: shrunk mean `(n x + k mu) / (n + k)`. Insiders: n complete decisions, x their
  mean 6m excess, k = 5, mu the mean complete 6m excess of every decision (each counted once,
  so a joint filing counts once). Funds: n complete quarters (a period whose next period has
  started), x the mean quarterly excess against SPY, k = 4, mu the mean over every fund's
  quarters. The rating is the shrunk mean's 0-100 percentile among profiles of the same kind,
  basis and toggle with n >= 1. Without complete data there is no shrunk mean, rating or
  confidence ("not enough data yet").

Runs replace the rows of the owners (or funds) in scope, then refresh the shrunk means and
ratings of every profile of that kind, because percentiles are relative.
"""

import math
import statistics
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, cast

import numpy as np
import pandas as pd
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from signals.analytics.copycat import Lot, SaleEvent, copycat_nav, empty_nav
from signals.analytics.entries import Entry, EntryKind
from signals.analytics.funds import (
    PRICE_LOOKBACK_DAYS,
    FundPeriodHoldings,
    fund_copycat_nav,
    fund_periods,
    fund_quarterly_excess,
    load_fund_inputs,
)
from signals.analytics.returns import sector_etf_for
from signals.analytics.series import BenchPanel, IssuerSeries, load_bench, load_issuer_series
from signals.analytics.types import WindowResult
from signals.analytics.windows import TRADING_DAYS_PER_YEAR, risk_label, window_stats
from signals.db.models import (
    Decision,
    DecisionOwner,
    DecisionReturn,
    FundFiling,
    FundManager,
    FundNavDaily,
    Issuer,
    ProfileStats,
    ProfileWindow,
)
from signals.domain.types import Basis, Confidence, Horizon, ProfileKind, RiskLabel, Window

INSIDER_K = 5.0
FUND_K = 4.0
BASES: tuple[Basis, ...] = (Basis.FILED, Basis.EXECUTED)
TOGGLES: tuple[bool, ...] = (False, True)


@dataclass(frozen=True)
class ProfileSummary:
    n_decisions: int
    n_buys: int
    n_sells: int
    n_complete: int
    avg_roi_6m: float | None
    avg_roi_6m_raw: float | None
    median_6m: float | None
    hit_rate: float | None
    best_decision_id: int | None
    worst_decision_id: int | None
    avg_lag_days: float | None
    avg_lag_cost: float | None


# ----------------------------------------------------------------------------- pure math
def _missing(value: Any) -> bool:
    return value is None or bool(pd.isna(value))


def _mean(values: Iterable[Any]) -> float | None:
    known = [float(v) for v in values if not _missing(v)]
    return sum(known) / len(known) if known else None


def _summarize_rows(
    decisions: Sequence[tuple[Any, Any, Any, Any]],
    returns_6m: Sequence[tuple[Any, Any, Any, Any]],
) -> ProfileSummary:
    """decisions: (id, direction, lag_days, lag_cost); returns_6m: (decision_id, raw_return,
    excess_spy, is_complete)."""
    ids = {int(d[0]) for d in decisions}
    scored = sorted(
        (
            (int(r[0]), r[1], float(r[2]))
            for r in returns_6m
            if int(r[0]) in ids and not _missing(r[3]) and bool(r[3]) and not _missing(r[2])
        ),
        key=lambda r: r[0],
    )
    excess = [r[2] for r in scored]
    n = len(scored)
    return ProfileSummary(
        n_decisions=len(decisions),
        n_buys=sum(1 for d in decisions if d[1] == "buy"),
        n_sells=sum(1 for d in decisions if d[1] == "sell"),
        n_complete=n,
        avg_roi_6m=sum(excess) / n if n else None,
        avg_roi_6m_raw=_mean(r[1] for r in scored),
        median_6m=float(statistics.median(excess)) if n else None,
        hit_rate=sum(1 for x in excess if x > 0) / n if n else None,
        best_decision_id=max(scored, key=lambda r: r[2])[0] if n else None,
        worst_decision_id=min(scored, key=lambda r: r[2])[0] if n else None,
        avg_lag_days=_mean(d[2] for d in decisions),
        avg_lag_cost=_mean(d[3] for d in decisions),
    )


def summarize(decisions: pd.DataFrame, returns_6m: pd.DataFrame) -> ProfileSummary:
    """`decisions` has columns id and direction (lag_days and lag_cost optional);
    `returns_6m` has decision_id, raw_return, excess_spy and is_complete. Averages, the
    median and the hit rate use complete rows with an SPY excess only."""

    def column(frame: pd.DataFrame, name: str) -> list[Any]:
        return list(frame[name]) if name in frame.columns else [None] * len(frame)

    return _summarize_rows(
        list(
            zip(
                column(decisions, "id"),
                column(decisions, "direction"),
                column(decisions, "lag_days"),
                column(decisions, "lag_cost"),
                strict=True,
            )
        ),
        list(
            zip(
                column(returns_6m, "decision_id"),
                column(returns_6m, "raw_return"),
                column(returns_6m, "excess_spy"),
                column(returns_6m, "is_complete"),
                strict=True,
            )
        ),
    )


def shrunk_mean(n: int, mean: float, mu: float, k: float) -> float:
    return (n * mean + k * mu) / (n + k)


def percentile_ratings(values: pd.Series) -> pd.Series:
    """round(100 x (rank - 1) / (n - 1)) over the known values, with average ranks for ties;
    50 when only one value is known; unknown values stay NaN."""
    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    known = numeric.notna()
    n = int(known.sum())
    out = pd.Series(np.nan, index=values.index, dtype=float)
    if n == 1:
        out[known] = 50.0
    elif n > 1:
        ranks = numeric[known].rank(method="average")
        out[known] = (100.0 * (ranks - 1.0) / (n - 1)).round()
    return out


def _confidence(n: int, *, low_below: int, high_above: int) -> Confidence | None:
    if n <= 0:
        return None
    if n < low_below:
        return Confidence.LOW
    if n <= high_above:
        return Confidence.MEDIUM
    return Confidence.HIGH


def confidence_insider(n: int) -> Confidence | None:
    return _confidence(n, low_below=5, high_above=15)


def confidence_fund(n: int) -> Confidence | None:
    return _confidence(n, low_below=4, high_above=12)


def _history_vol(nav: pd.DataFrame, as_of: date) -> float | None:
    values = np.array([v for d, v in zip(nav.index, nav["nav"], strict=True) if d <= as_of])
    if len(values) < 3:
        return None
    daily = values[1:] / values[:-1] - 1
    vol = float(np.std(daily, ddof=1)) * math.sqrt(TRADING_DAYS_PER_YEAR)
    return vol if math.isfinite(vol) else None


def _profile_risk(
    nav: pd.DataFrame, windows: Sequence[WindowResult], as_of: date
) -> RiskLabel | None:
    """Risk label from the 5y window's volatility, else the full history's."""
    five = next((w.vol for w in windows if w.window == Window.Y5), None)
    return risk_label(five if five is not None else _history_vol(nav, as_of))


# ----------------------------------------------------------------------------- insiders
@dataclass(frozen=True)
class _Decision:
    id: int
    issuer_cik: int
    direction: str
    is_planned: bool
    last_trade_date: date
    lag_days: int | None
    lag_cost: float | None
    sell_fraction: float | None


@dataclass(frozen=True)
class _InsiderBook:
    decisions: dict[int, _Decision]
    owners: dict[int, list[int]]  # owner cik -> decision ids
    six_month: dict[tuple[int, str], tuple[Any, Any, Any]]  # (id, basis) -> raw, excess, done
    entries: dict[tuple[int, str], Entry]  # (id, basis) -> the follower's entry


def _load_insider_book(session: Session, owner_ciks: Collection[int] | None) -> _InsiderBook:
    query = select(
        DecisionOwner.owner_cik,
        Decision.id,
        Decision.issuer_cik,
        Decision.direction,
        Decision.is_planned,
        Decision.last_trade_date,
        Decision.lag_days,
        Decision.lag_cost,
        Decision.sell_fraction,
    ).join(Decision, Decision.id == DecisionOwner.decision_id)
    if owner_ciks is not None:
        query = query.where(DecisionOwner.owner_cik.in_(list(owner_ciks)))
    decisions: dict[int, _Decision] = {}
    owners: dict[int, list[int]] = {}
    for r in session.execute(query.order_by(DecisionOwner.owner_cik, Decision.id)):
        if r.id not in decisions:
            decisions[r.id] = _Decision(
                r.id,
                r.issuer_cik,
                r.direction,
                r.is_planned,
                r.last_trade_date,
                r.lag_days,
                r.lag_cost,
                r.sell_fraction,
            )
        owners.setdefault(r.owner_cik, []).append(r.id)

    six = select(
        DecisionReturn.decision_id,
        DecisionReturn.basis,
        DecisionReturn.raw_return,
        DecisionReturn.excess_spy,
        DecisionReturn.is_complete,
    ).where(DecisionReturn.horizon == Horizon.M6.value)
    entries = (
        select(
            DecisionReturn.decision_id,
            DecisionReturn.basis,
            DecisionReturn.entry_date,
            DecisionReturn.entry_price_adj,
            DecisionReturn.entry_kind,
        )
        .where(
            DecisionReturn.entry_date.is_not(None),
            DecisionReturn.entry_price_adj.is_not(None),
            DecisionReturn.entry_kind.is_not(None),
        )
        .ext(distinct_on(DecisionReturn.decision_id, DecisionReturn.basis))
        .order_by(DecisionReturn.decision_id, DecisionReturn.basis, DecisionReturn.horizon)
    )
    if owner_ciks is not None:
        ids = list(decisions)
        six = six.where(DecisionReturn.decision_id.in_(ids))
        entries = entries.where(DecisionReturn.decision_id.in_(ids))
    six_month = {
        (r.decision_id, r.basis): (r.raw_return, r.excess_spy, r.is_complete)
        for r in session.execute(six)
        if r.decision_id in decisions
    }
    entry_of = {
        (r.decision_id, r.basis): Entry(
            r.entry_date, float(r.entry_price_adj), cast(EntryKind, r.entry_kind)
        )
        for r in session.execute(entries)
        if r.decision_id in decisions
    }
    return _InsiderBook(decisions, owners, six_month, entry_of)


def _issuer_sectors(session: Session, issuer_ciks: Collection[int]) -> dict[int, str | None]:
    if not issuer_ciks:
        return {}
    rows = session.execute(
        select(Issuer.cik, Issuer.sector).where(Issuer.cik.in_(list(issuer_ciks)))
    )
    return {cik: sector for cik, sector in rows}


def _lot_starts(book: _InsiderBook, decisions: Iterable[_Decision]) -> dict[int, date]:
    """Earliest buy entry per issuer (any basis): where its price series must start."""
    starts: dict[int, date] = {}
    for d in decisions:
        if d.direction != "buy":
            continue
        for basis in BASES:
            entry = book.entries.get((d.id, basis.value))
            if entry is not None:
                starts[d.issuer_cik] = min(starts.get(d.issuer_cik, entry.date), entry.date)
    return starts


def _series_loader(
    session: Session, starts: Mapping[int, date], end: date
) -> Callable[[int], IssuerSeries]:
    cache: dict[int, IssuerSeries] = {}

    def series_of(issuer_cik: int) -> IssuerSeries:
        if issuer_cik not in cache:
            start = starts.get(issuer_cik, end)
            cache[issuer_cik] = load_issuer_series(session, issuer_cik, start, end)
        return cache[issuer_cik]

    return series_of


def _owner_nav(
    decisions: Sequence[_Decision],
    basis: str,
    entries: Mapping[tuple[int, str], Entry],
    series_of: Callable[[int], IssuerSeries],
    sector_etf_of: Callable[[int], str | None],
    bench: BenchPanel,
    as_of: date,
) -> pd.DataFrame:
    """The owner's copycat on `basis`: a lot per buy, a sale per sell with a known fraction,
    each at its own entry; from the first lot's entry to `as_of` (empty without lots)."""
    lots: list[Lot] = []
    sales: list[SaleEvent] = []
    for d in decisions:
        entry = entries.get((d.id, basis))
        if entry is None:
            continue
        if d.direction == "buy":
            lots.append(
                Lot(d.id, d.issuer_cik, series_of(d.issuer_cik), entry, sector_etf_of(d.issuer_cik))
            )
        elif d.sell_fraction is not None:
            sales.append(SaleEvent(d.issuer_cik, entry, d.sell_fraction))
    start = min((lot.entry.date for lot in lots), default=None)
    if start is None or start > as_of:
        return empty_nav()
    return copycat_nav(lots, sales, bench, start, as_of)


def _primary_issuer(decisions: Sequence[_Decision]) -> int | None:
    """The issuer with the most decisions (ties: the latest trade, then the lowest CIK)."""
    if not decisions:
        return None
    counts = Counter(d.issuer_cik for d in decisions)
    latest: dict[int, date] = {}
    for d in decisions:
        latest[d.issuer_cik] = max(latest.get(d.issuer_cik, d.last_trade_date), d.last_trade_date)
    return max(counts, key=lambda cik: (counts[cik], latest[cik], -cik))


def _value(enum: Confidence | RiskLabel | None) -> str | None:
    return None if enum is None else enum.value


def _window_rows(
    kind: str, cik: int, basis: str, include: bool, windows: Sequence[WindowResult]
) -> list[dict[str, Any]]:
    return [
        {
            "kind": kind,
            "cik": cik,
            "basis": basis,
            "include_10b5_1": include,
            "window": Window(w.window).value,
            "start_date": w.start,
            "end_date": w.end,
            "ret": w.ret,
            "ret_spy": w.ret_spy,
            "ret_qqq": w.ret_qqq,
            "ret_sector": w.ret_sector,
            "annualized": w.annualized,
            "vol": w.vol,
            "max_drawdown": w.max_drawdown,
            "beta": w.beta,
            "time_invested_pct": w.time_invested_pct,
        }
        for w in windows
    ]


def _summary_columns(s: ProfileSummary) -> dict[str, Any]:
    return {
        "n_decisions": s.n_decisions,
        "n_buys": s.n_buys,
        "n_sells": s.n_sells,
        "n_complete": s.n_complete,
        "avg_roi_6m": s.avg_roi_6m,
        "avg_roi_6m_raw": s.avg_roi_6m_raw,
        "median_6m": s.median_6m,
        "hit_rate": s.hit_rate,
        "best_decision_id": s.best_decision_id,
        "worst_decision_id": s.worst_decision_id,
        "avg_lag_days": s.avg_lag_days,
        "avg_lag_cost": s.avg_lag_cost,
        "shrunk_mean": None,  # set with the rating, over the whole population
        "rating": None,
    }


def _delete_profiles(session: Session, kind: str, ciks: Collection[int] | None) -> None:
    stats = delete(ProfileStats).where(ProfileStats.kind == kind)
    windows = delete(ProfileWindow).where(ProfileWindow.kind == kind)
    if ciks is not None:
        stats = stats.where(ProfileStats.cik.in_(list(ciks)))
        windows = windows.where(ProfileWindow.cik.in_(list(ciks)))
    session.execute(stats)
    session.execute(windows)


def _insert(session: Session, model: type, rows: Sequence[dict[str, Any]]) -> None:
    if rows:
        session.execute(insert(model), list(rows))


def compute_profile_stats(
    session: Session, *, owner_ciks: Collection[int] | None = None, as_of: date
) -> int:
    """Replace insider `profile_stats` (4 rows per owner: basis x toggle) and their
    `profile_windows` for the owners (or all), then refresh every insider's shrunk mean and
    rating. Returns the number of `profile_stats` rows written."""
    kind = ProfileKind.INSIDER.value
    _delete_profiles(session, kind, owner_ciks)
    book = _load_insider_book(session, owner_ciks)
    sectors = _issuer_sectors(session, {d.issuer_cik for d in book.decisions.values()})
    starts = _lot_starts(book, book.decisions.values())
    bench = load_bench(session, min(starts.values()), as_of) if starts else BenchPanel({})
    series_of = _series_loader(session, starts, as_of)

    def sector_etf_of(issuer_cik: int) -> str | None:
        return sector_etf_for(sectors.get(issuer_cik))

    stats_rows: list[dict[str, Any]] = []
    window_rows: list[dict[str, Any]] = []
    for owner, ids in book.owners.items():
        mine = [book.decisions[i] for i in ids]
        primary = _primary_issuer(mine)
        for include in TOGGLES:
            chosen = [d for d in mine if include or not d.is_planned]
            facts = [(d.id, d.direction, d.lag_days, d.lag_cost) for d in chosen]
            for basis in BASES:
                six = [
                    (d.id, *book.six_month[(d.id, basis.value)])
                    for d in chosen
                    if (d.id, basis.value) in book.six_month
                ]
                summary = _summarize_rows(facts, six)
                nav = _owner_nav(
                    chosen, basis.value, book.entries, series_of, sector_etf_of, bench, as_of
                )
                windows = window_stats(nav, as_of)
                stats_rows.append(
                    {
                        "kind": kind,
                        "cik": owner,
                        "basis": basis.value,
                        "include_10b5_1": include,
                        **_summary_columns(summary),
                        "confidence": _value(confidence_insider(summary.n_complete)),
                        "risk_label": _value(_profile_risk(nav, windows, as_of)),
                        "primary_issuer_cik": primary,
                        "sector": sectors.get(primary) if primary is not None else None,
                        "last_trade_date": max((d.last_trade_date for d in chosen), default=None),
                    }
                )
                window_rows.extend(_window_rows(kind, owner, basis.value, include, windows))
    _insert(session, ProfileStats, stats_rows)
    _insert(session, ProfileWindow, window_rows)
    _refresh_ratings(session, kind, _insider_population_means(session), INSIDER_K)
    return len(stats_rows)


def insider_nav(
    session: Session, cik: int, *, basis: Basis | str, include_10b5_1: bool, as_of: date
) -> pd.DataFrame:
    """One owner's copycat frame (nav, spy, qqq, sector, invested), built exactly as
    `compute_profile_stats` builds it for `profile_windows`; empty without buy entries."""
    book = _load_insider_book(session, [cik])
    chosen = [
        book.decisions[i]
        for i in book.owners.get(cik, [])
        if include_10b5_1 or not book.decisions[i].is_planned
    ]
    starts = _lot_starts(book, chosen)
    if not starts:
        return empty_nav()
    sectors = _issuer_sectors(session, set(starts))

    def sector_etf_of(issuer_cik: int) -> str | None:
        return sector_etf_for(sectors.get(issuer_cik))

    return _owner_nav(
        chosen,
        Basis(basis).value,
        book.entries,
        _series_loader(session, starts, as_of),
        sector_etf_of,
        load_bench(session, min(starts.values()), as_of),
        as_of,
    )


# ----------------------------------------------------------------------------- ratings
def _insider_population_means(session: Session) -> dict[tuple[str, bool], float]:
    """Mean complete 6m excess per (basis, toggle), every decision counted once."""
    rows = session.execute(
        select(
            DecisionReturn.basis,
            Decision.is_planned,
            func.sum(DecisionReturn.excess_spy),
            func.count(),
        )
        .join(Decision, Decision.id == DecisionReturn.decision_id)
        .where(
            DecisionReturn.horizon == Horizon.M6.value,
            DecisionReturn.is_complete.is_(True),
            DecisionReturn.excess_spy.is_not(None),
        )
        .group_by(DecisionReturn.basis, Decision.is_planned)
    ).all()
    sums: dict[tuple[str, bool], tuple[float, int]] = {}
    for basis, planned, total, count in rows:
        for include in TOGGLES:
            if planned and not include:
                continue
            s, c = sums.get((basis, include), (0.0, 0))
            sums[(basis, include)] = (s + float(total or 0.0), c + int(count))
    return {key: s / c for key, (s, c) in sums.items() if c}


def _fund_population_means(session: Session) -> dict[tuple[str, bool], float]:
    """Mean quarterly excess over every tracked fund's complete quarters, per basis."""
    rows = session.execute(
        select(
            ProfileStats.basis,
            ProfileStats.include_10b5_1,
            func.sum(ProfileStats.n_complete * ProfileStats.avg_roi_6m),
            func.sum(ProfileStats.n_complete),
        )
        .where(
            ProfileStats.kind == ProfileKind.FUND.value,
            ProfileStats.n_complete >= 1,
            ProfileStats.avg_roi_6m.is_not(None),
        )
        .group_by(ProfileStats.basis, ProfileStats.include_10b5_1)
    ).all()
    return {(basis, include): float(s) / int(n) for basis, include, s, n in rows if n}


def _refresh_ratings(
    session: Session, kind: str, means: Mapping[tuple[str, bool], float], k: float
) -> None:
    """Shrunk mean and percentile rating for every profile of `kind`."""
    rows = session.execute(
        select(
            ProfileStats.cik,
            ProfileStats.basis,
            ProfileStats.include_10b5_1,
            ProfileStats.n_complete,
            ProfileStats.avg_roi_6m,
        ).where(ProfileStats.kind == kind)
    ).all()
    if not rows:
        return
    shrunk: list[float | None] = []
    for _, basis, include, n, mean in rows:
        mu = means.get((basis, include))
        if n >= 1 and mean is not None and mu is not None:
            shrunk.append(shrunk_mean(n, mean, mu, k))
        else:
            shrunk.append(None)
    frame = pd.DataFrame(
        {
            "group": [f"{r.basis}|{r.include_10b5_1}" for r in rows],
            "shrunk": pd.Series(shrunk, dtype=float),
        }
    )
    ratings = frame.groupby("group")["shrunk"].transform(percentile_ratings)
    session.execute(
        update(ProfileStats),
        [
            {
                "kind": kind,
                "cik": r.cik,
                "basis": r.basis,
                "include_10b5_1": r.include_10b5_1,
                "shrunk_mean": s,
                "rating": None if pd.isna(rating) else int(rating),
            }
            for r, s, rating in zip(rows, shrunk, ratings, strict=True)
        ],
    )


# ----------------------------------------------------------------------------- funds
def _optional(value: Any) -> float | None:
    return None if _missing(value) else float(value)


def _fund_nav_rows(cik: int, basis: str, nav: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "cik": cik,
            "basis": basis,
            "date": d,
            "nav": float(value),
            "nav_spy": _optional(spy),
            "nav_qqq": _optional(qqq),
            "nav_sector": _optional(sector),
            "coverage": _optional(coverage),
        }
        for d, value, spy, qqq, sector, coverage in zip(
            nav.index,
            nav["nav"],
            nav["spy"],
            nav["qqq"],
            nav["sector"],
            nav["coverage"],
            strict=True,
        )
    ]


def _fund_summary(
    periods: Sequence[FundPeriodHoldings], excess: Sequence[float], as_of: date
) -> ProfileSummary:
    n = len(excess)
    return ProfileSummary(
        n_decisions=sum(1 for p in periods if p.start <= as_of),
        n_buys=0,
        n_sells=0,
        n_complete=n,
        avg_roi_6m=sum(excess) / n if n else None,
        avg_roi_6m_raw=None,
        median_6m=float(statistics.median(excess)) if n else None,
        hit_rate=sum(1 for x in excess if x > 0) / n if n else None,
        best_decision_id=None,
        worst_decision_id=None,
        avg_lag_days=None,
        avg_lag_cost=None,
    )


def compute_fund_stats(
    session: Session, *, filer_ciks: Collection[int] | None = None, as_of: date
) -> int:
    """For every tracked fund (or those given, if tracked) and basis: the copycat curve into
    `fund_nav_daily`, its windows into `profile_windows` and its stats into `profile_stats`
    (include_10b5_1 false), replacing those funds' rows; then refresh every fund's shrunk
    mean and rating. Returns the number of `profile_stats` rows written."""
    kind = ProfileKind.FUND.value
    _delete_profiles(session, kind, filer_ciks)
    nav_scope = delete(FundNavDaily)
    tracked = select(FundManager.cik).where(FundManager.is_tracked.is_(True))
    if filer_ciks is not None:
        nav_scope = nav_scope.where(FundNavDaily.cik.in_(list(filer_ciks)))
        tracked = tracked.where(FundManager.cik.in_(list(filer_ciks)))
    session.execute(nav_scope)
    funds = list(session.scalars(tracked.order_by(FundManager.cik)))

    stats_rows: list[dict[str, Any]] = []
    window_rows: list[dict[str, Any]] = []
    first = (
        session.scalar(
            select(func.min(FundFiling.period_of_report)).where(FundFiling.filer_cik.in_(funds))
        )
        if funds
        else None
    )
    bench = (
        load_bench(session, first - timedelta(days=PRICE_LOOKBACK_DAYS), as_of)
        if first is not None
        else BenchPanel({})
    )
    for cik in funds:
        inputs = load_fund_inputs(session, cik, end=as_of)
        for basis in BASES:
            periods = fund_periods(inputs, basis)
            nav = fund_copycat_nav(
                periods, inputs.panel, bench, end=as_of, sector_etfs=inputs.sector_etfs
            )
            _insert(session, FundNavDaily, _fund_nav_rows(cik, basis.value, nav))
            # the fund copycat holds its priced positions whenever a period is in force
            windows = window_stats(nav.assign(invested=(nav["coverage"] > 0).astype(float)), as_of)
            summary = _fund_summary(
                periods, fund_quarterly_excess(nav, [p.start for p in periods]), as_of
            )
            stats_rows.append(
                {
                    "kind": kind,
                    "cik": cik,
                    "basis": basis.value,
                    "include_10b5_1": False,
                    **_summary_columns(summary),
                    "confidence": _value(confidence_fund(summary.n_complete)),
                    "risk_label": _value(_profile_risk(nav, windows, as_of)),
                    "primary_issuer_cik": None,
                    "sector": None,
                    "last_trade_date": None,
                }
            )
            window_rows.extend(_window_rows(kind, cik, basis.value, False, windows))
    _insert(session, ProfileStats, stats_rows)
    _insert(session, ProfileWindow, window_rows)
    _refresh_ratings(session, kind, _fund_population_means(session), FUND_K)
    return len(stats_rows)
