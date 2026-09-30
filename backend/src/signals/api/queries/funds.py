"""Queries behind the `/funds/{cik}` endpoints.

Fund stats mapping (see the E5 ledger ruling): `profile_stats(kind='fund', ...)` stores
quarterly numbers in the same columns insiders use for 6-month decisions (avg_roi_6m,
median_6m, hit_rate, n_complete quarters, n_decisions = 13F periods started). None of that
row is exposed directly by FundHeader or FundHoldingsOut -- the only field derived from it
here is `rating`, via the shared `rating_of()` (Rating.n = n_complete = quarters, unchanged
by kind). The fuller mapping (avg_roi_6m/hit_rate/windows as fund columns) belongs to the
screener's FundScreenRow (E6), not this file.
"""

from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from signals.api.pagination import SortKey, paginate, parse_float, parse_str
from signals.api.queries.common import WINDOW_ORDER, rating_of
from signals.api.schemas import (
    AllocationSlice,
    FundHeader,
    FundHoldingRow,
    FundHoldingsOut,
    FundValuePoint,
    SecurityRef,
    WindowStat,
)
from signals.db.models import (
    FundManager,
    FundNavDaily,
    FundPosition,
    FundPositionChange,
    Issuer,
    Owner,
    ProfileStats,
    ProfileWindow,
    Security,
)
from signals.domain.portfolio import (
    allocation_slices,
    effective_n,
    fund_high_conviction,
    top5_weight,
)

FUND_HOLDING_KEYS = [
    SortKey("v", FundPositionChange.value_usd, desc=True, nullable=True, parse=parse_float),
    SortKey("c", FundPositionChange.cusip, desc=True, parse=parse_str),
    SortKey("p", FundPositionChange.put_call, desc=True, parse=parse_str),
]


def _window_stat(row: ProfileWindow) -> WindowStat:
    return WindowStat(
        window=row.window,  # type: ignore[arg-type]
        ret=row.ret,
        ret_spy=row.ret_spy,
        ret_qqq=row.ret_qqq,
        ret_sector=row.ret_sector,
        annualized=row.annualized,
        vol=row.vol,
        max_drawdown=row.max_drawdown,
        beta=row.beta,
        time_invested_pct=row.time_invested_pct,
    )


def _value_history(session: Session, cik: int) -> list[FundValuePoint]:
    rows = session.execute(
        select(FundPosition.period, FundPosition.value_usd, FundPosition.put_call).where(
            FundPosition.filer_cik == cik, FundPosition.is_effective.is_(True)
        )
    ).all()
    by_period: dict[date, list[tuple[float | None, str]]] = {}
    for period, value, put_call in rows:
        by_period.setdefault(period, []).append((value, put_call))
    return [
        FundValuePoint(
            period=period,
            value_usd=sum(v or 0.0 for v, _ in items),
            positions=sum(1 for _, pc in items if pc == ""),
        )
        for period, items in sorted(by_period.items())
    ]


def get_fund_header(session: Session, cik: int) -> FundHeader:
    manager = session.get(FundManager, cik)
    if manager is None:
        raise HTTPException(404, "fund not found")

    stats = session.get(ProfileStats, ("fund", cik, "filed", False))
    window_rows = {
        row.window: row
        for row in session.execute(
            select(ProfileWindow).where(
                ProfileWindow.kind == "fund",
                ProfileWindow.cik == cik,
                ProfileWindow.basis == "filed",
                ProfileWindow.include_10b5_1.is_(False),
            )
        ).scalars()
    }
    windows = [_window_stat(window_rows[name]) for name in WINDOW_ORDER if name in window_rows]

    coverage_pct = session.execute(
        select(FundNavDaily.coverage)
        .where(FundNavDaily.cik == cik, FundNavDaily.basis == "filed")
        .order_by(FundNavDaily.date.desc())
        .limit(1)
    ).scalar_one_or_none()

    insider_cik = cik if session.get(Owner, cik) is not None else None

    return FundHeader(
        cik=cik,
        name=manager.name,
        is_tracked=manager.is_tracked,
        latest_period=manager.latest_period,
        latest_value_usd=manager.latest_value_usd,
        latest_positions=manager.latest_positions,
        value_history=_value_history(session, cik),
        rating=rating_of(stats),
        windows=windows,
        coverage_pct=coverage_pct,
        insider_cik=insider_cik,
    )


def _security_ref(security: Security | None, cusip: str) -> SecurityRef:
    if security is None:
        return SecurityRef(cusip=cusip, name=None, ticker=None, issuer_cik=None)
    return SecurityRef(
        cusip=cusip, name=security.name, ticker=security.ticker, issuer_cik=security.issuer_cik
    )


def get_fund_holdings(
    session: Session, cik: int, *, period: date | None, cursor: str | None, limit: int
) -> FundHoldingsOut:
    manager = session.get(FundManager, cik)
    if manager is None:
        raise HTTPException(404, "fund not found")

    periods_available = sorted(
        set(
            session.execute(
                select(FundPositionChange.period)
                .where(FundPositionChange.filer_cik == cik)
                .distinct()
            ).scalars()
        ),
        reverse=True,
    )
    if not periods_available:
        return FundHoldingsOut(
            period=None,
            periods_available=[],
            rows=[],
            exits=[],
            by_sector=[],
            effective_n=None,
            top5_weight=None,
            next_cursor=None,
        )
    target = period or manager.latest_period or periods_available[0]

    all_changes = list(
        session.execute(
            select(FundPositionChange).where(
                FundPositionChange.filer_cik == cik, FundPositionChange.period == target
            )
        ).scalars()
    )
    exits = [c for c in all_changes if c.change == "EXIT"]
    non_exit_all = [c for c in all_changes if c.change != "EXIT"]

    securities = {
        s.cusip: s
        for s in session.execute(
            select(Security).where(Security.cusip.in_({c.cusip for c in all_changes}))
        ).scalars()
    }
    issuer_ciks = {s.issuer_cik for s in securities.values() if s.issuer_cik is not None}
    sectors = {
        i.cik: i.sector
        for i in session.execute(select(Issuer).where(Issuer.cik.in_(issuer_ciks))).scalars()
    }

    def _sector_for(cusip: str) -> str | None:
        sec = securities.get(cusip)
        return sectors.get(sec.issuer_cik) if sec and sec.issuer_cik is not None else None

    weights = [c.weight for c in non_exit_all]
    conviction_flags = fund_high_conviction(
        weights, [c.change for c in non_exit_all], [c.value_usd or 0.0 for c in non_exit_all]
    )
    conviction_by_key = {
        (c.cusip, c.put_call): flag for c, flag in zip(non_exit_all, conviction_flags, strict=True)
    }

    stmt = select(FundPositionChange).where(
        FundPositionChange.filer_cik == cik,
        FundPositionChange.period == target,
        FundPositionChange.change != "EXIT",
    )
    rows, next_cursor = paginate(session, stmt, FUND_HOLDING_KEYS, cursor, limit)
    changes = [row[0] for row in rows]

    def _row_out(c: FundPositionChange) -> FundHoldingRow:
        return FundHoldingRow(
            security=_security_ref(securities.get(c.cusip), c.cusip),
            put_call=c.put_call or None,
            shares=c.shares or 0.0,
            value_usd=c.value_usd or 0.0,
            weight=c.weight,
            prev_weight=c.prev_weight,
            change=c.change,  # type: ignore[arg-type]
            shares_change_pct=c.shares_change_pct,
            sector=_sector_for(c.cusip),
            high_conviction=conviction_by_key.get((c.cusip, c.put_call), False),
        )

    by_sector_value: dict[str, float] = {}
    for c in non_exit_all:
        key = _sector_for(c.cusip) or "Unknown"
        by_sector_value[key] = by_sector_value.get(key, 0.0) + (c.value_usd or 0.0)
    by_sector = [AllocationSlice.model_validate(s) for s in allocation_slices(by_sector_value)]

    clean_weights = [w for w in weights if w is not None]
    return FundHoldingsOut(
        period=target,
        periods_available=periods_available,
        rows=[_row_out(c) for c in changes],
        exits=[_row_out(c) for c in exits],
        by_sector=by_sector,
        effective_n=effective_n(clean_weights),
        top5_weight=top5_weight(clean_weights),
        next_cursor=next_cursor,
    )
