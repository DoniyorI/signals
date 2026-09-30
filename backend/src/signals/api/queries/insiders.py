"""Queries behind the `/insiders/{cik}` endpoints."""

from collections.abc import Sequence
from datetime import timedelta
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signals.api.pagination import SortKey, paginate, parse_date, parse_int, parse_str
from signals.api.queries.common import (
    HORIZON_ORDER,
    current_symbols,
    curve_points,
    issuer_ref,
    issuer_refs,
    latest_close,
    ordered_windows,
    rating_of,
    sec_url,
    today,
    window_stat,
)
from signals.api.schemas import (
    AllocationSlice,
    DecisionOut,
    DecisionPage,
    Form144Out,
    HoldingOut,
    HoldingsOut,
    HorizonReturn,
    InsiderHeader,
    OwnerRef,
    PerformanceOut,
    Rating,
    RoleAtIssuer,
    TransactionOut,
    TransactionPage,
)
from signals.db.models import (
    Decision,
    DecisionOwner,
    DecisionReturn,
    Filing,
    FilingOwner,
    Form144Notice,
    FundManager,
    InsiderHolding,
    InsiderTransaction,
    Issuer,
    Owner,
    OwnerRole,
    Position,
    ProfileStats,
)
from signals.domain.portfolio import allocation_slices, effective_n, top5_weight
from signals.domain.types import CODE_LABELS

DECISION_KEYS = [
    SortKey("t", Decision.first_trade_date, desc=True, parse=parse_date),
    SortKey("k", Decision.id, desc=True, parse=parse_int),
]

TRANSACTION_KEYS = [
    SortKey("d", InsiderTransaction.transaction_date, desc=True, nullable=True, parse=parse_date),
    SortKey("a", InsiderTransaction.accession_no, desc=True, parse=parse_str),
    SortKey("r", InsiderTransaction.row_no, desc=False, parse=parse_int),
]


# --------------------------------------------------------------------------- header
def _roles_at_issuer(session: Session, cik: int) -> list[RoleAtIssuer]:
    rows = list(
        session.execute(
            select(OwnerRole).where(OwnerRole.owner_cik == cik).order_by(OwnerRole.issuer_cik)
        ).scalars()
    )
    issuers = issuer_refs(session, [r.issuer_cik for r in rows])
    return [
        RoleAtIssuer(
            issuer=issuers[row.issuer_cik],
            roles=list(row.roles or []),
            officer_title=row.officer_title,
            first_filed=row.first_filed,
            last_filed=row.last_filed,
        )
        for row in rows
    ]


def _decision_counts(session: Session, cik: int, include_10b5_1: bool) -> tuple[int, int, int]:
    """n_decisions/n_buys/n_sells computed straight from decisions, for insiders with no
    profile_stats row yet (see rating_of: a missing row means "not enough data")."""
    stmt = (
        select(Decision.direction, func.count())
        .join(DecisionOwner, DecisionOwner.decision_id == Decision.id)
        .where(DecisionOwner.owner_cik == cik)
    )
    if not include_10b5_1:
        stmt = stmt.where(Decision.is_planned.is_(False))
    counts = dict(session.execute(stmt.group_by(Decision.direction)).all())
    n_buys, n_sells = counts.get("buy", 0), counts.get("sell", 0)
    return n_buys + n_sells, n_buys, n_sells


def get_insider_header(
    session: Session, cik: int, *, basis: str, include_10b5_1: bool
) -> InsiderHeader:
    owner = session.get(Owner, cik)
    if owner is None:
        raise HTTPException(404, "insider not found")

    stats = session.get(ProfileStats, ("insider", cik, basis, include_10b5_1))
    risk_label: Literal["low", "medium", "high"] | None
    if stats is None:
        n_decisions, n_buys, n_sells = _decision_counts(session, cik, include_10b5_1)
        rating = Rating(score=None, confidence=None, n=0)
        avg_roi_6m = avg_roi_6m_raw = median_6m = hit_rate = None
        avg_lag_days = avg_lag_cost = None
        risk_label = None
        best = worst = None
        updated_at = None
    else:
        n_decisions, n_buys, n_sells = stats.n_decisions, stats.n_buys, stats.n_sells
        rating = rating_of(stats)
        avg_roi_6m, avg_roi_6m_raw = stats.avg_roi_6m, stats.avg_roi_6m_raw
        median_6m, hit_rate = stats.median_6m, stats.hit_rate
        avg_lag_days, avg_lag_cost = stats.avg_lag_days, stats.avg_lag_cost
        risk_label = stats.risk_label  # type: ignore[assignment]
        best = _decision_out_by_id(session, stats.best_decision_id, basis)
        worst = _decision_out_by_id(session, stats.worst_decision_id, basis)
        updated_at = stats.updated_at

    fund_cik = cik if session.get(FundManager, cik) is not None else None
    return InsiderHeader(
        cik=cik,
        name=owner.name,
        owner_type=owner.owner_type,  # type: ignore[arg-type]
        roles=_roles_at_issuer(session, cik),
        basis=basis,  # type: ignore[arg-type]
        include_10b5_1=include_10b5_1,
        rating=rating,
        avg_roi_6m=avg_roi_6m,
        avg_roi_6m_raw=avg_roi_6m_raw,
        median_6m=median_6m,
        hit_rate=hit_rate,
        n_decisions=n_decisions,
        n_buys=n_buys,
        n_sells=n_sells,
        avg_lag_days=avg_lag_days,
        avg_lag_cost=avg_lag_cost,
        best=best,
        worst=worst,
        risk_label=risk_label,
        fund_cik=fund_cik,
        updated_at=updated_at,
    )


# --------------------------------------------------------------------------- decisions
def _decision_owner_refs(session: Session, decision_id: int) -> list[OwnerRef]:
    rows = session.execute(
        select(Owner.cik, Owner.name)
        .join(DecisionOwner, DecisionOwner.owner_cik == Owner.cik)
        .where(DecisionOwner.decision_id == decision_id)
        .order_by(Owner.cik)
    ).all()
    return [OwnerRef(cik=row.cik, name=row.name) for row in rows]


def _horizon_returns(session: Session, decision_id: int, basis: str) -> list[HorizonReturn]:
    rows = {
        row.horizon: row
        for row in session.execute(
            select(DecisionReturn).where(
                DecisionReturn.decision_id == decision_id, DecisionReturn.basis == basis
            )
        ).scalars()
    }
    return [
        HorizonReturn(
            horizon=horizon,  # type: ignore[arg-type]
            raw=rows[horizon].raw_return if horizon in rows else None,
            excess_spy=rows[horizon].excess_spy if horizon in rows else None,
            excess_qqq=rows[horizon].excess_qqq if horizon in rows else None,
            excess_sector=rows[horizon].excess_sector if horizon in rows else None,
            complete=rows[horizon].is_complete if horizon in rows else False,
        )
        for horizon in HORIZON_ORDER
    ]


def _decision_out(session: Session, decision: Decision, basis: str) -> DecisionOut:
    owners = _decision_owner_refs(session, decision.id)
    link_cik = owners[0].cik if owners else decision.issuer_cik
    return DecisionOut(
        id=decision.id,
        issuer=issuer_ref(session, decision.issuer_cik),
        owners=owners,
        direction=decision.direction,  # type: ignore[arg-type]
        first_trade_date=decision.first_trade_date,
        last_trade_date=decision.last_trade_date,
        shares=decision.shares,
        value_usd=decision.value_usd,
        vwap=decision.vwap,
        stake_change_pct=decision.stake_change_pct,
        accepted_at=decision.accepted_at,
        plan_10b5_1=decision.plan_10b5_1,  # type: ignore[arg-type]
        badges=list(decision.badges or []),
        lag_days=decision.lag_days,
        lag_cost=decision.lag_cost,
        returns=_horizon_returns(session, decision.id, basis),
        first_accession=decision.first_accession,
        sec_url=sec_url(link_cik, decision.first_accession),
    )


def _decision_out_by_id(
    session: Session, decision_id: int | None, basis: str
) -> DecisionOut | None:
    if decision_id is None:
        return None
    decision = session.get(Decision, decision_id)
    return _decision_out(session, decision, basis) if decision is not None else None


def list_decisions(
    session: Session,
    cik: int,
    *,
    basis: str,
    include_10b5_1: bool,
    direction: str | None,
    cursor: str | None,
    limit: int,
) -> DecisionPage:
    stmt = (
        select(Decision)
        .join(DecisionOwner, DecisionOwner.decision_id == Decision.id)
        .where(DecisionOwner.owner_cik == cik)
    )
    if not include_10b5_1:
        stmt = stmt.where(Decision.is_planned.is_(False))
    if direction:
        stmt = stmt.where(Decision.direction == direction)
    rows, next_cursor = paginate(session, stmt, DECISION_KEYS, cursor, limit)
    items = [_decision_out(session, row[0], basis) for row in rows]
    return DecisionPage(items=items, next_cursor=next_cursor)


# --------------------------------------------------------------------------- transactions
def _transaction_out(
    session: Session, tx: InsiderTransaction, filing: Filing, link_cik: int
) -> TransactionOut:
    return TransactionOut(
        accession_no=tx.accession_no,
        sec_url=sec_url(link_cik, tx.accession_no),
        form_type=filing.form_type,
        accepted_at=filing.accepted_at,
        issuer=issuer_ref(session, tx.issuer_cik),
        transaction_date=tx.transaction_date,
        code=tx.code,
        code_label=CODE_LABELS.get(tx.code) if tx.code else None,
        acquired_disposed=tx.acquired_disposed,
        shares=tx.shares,
        price=tx.price,
        value_usd=tx.value_usd,
        shares_owned_after=tx.shares_owned_after,
        direct_indirect=tx.direct_indirect,
        security_title=tx.security_title,
        table_kind=tx.table_kind,  # type: ignore[arg-type]
        plan_10b5_1=tx.plan_10b5_1,  # type: ignore[arg-type]
        superseded=tx.superseded_by is not None,
        footnotes=list((tx.footnotes or {}).values()),
    )


def list_transactions(
    session: Session,
    cik: int,
    *,
    codes: Sequence[str] | None,
    issuer_cik: int | None,
    include_superseded: bool,
    cursor: str | None,
    limit: int,
) -> TransactionPage:
    stmt = (
        select(InsiderTransaction)
        .join(FilingOwner, FilingOwner.accession_no == InsiderTransaction.accession_no)
        .where(FilingOwner.owner_cik == cik)
    )
    if not include_superseded:
        stmt = stmt.where(InsiderTransaction.superseded_by.is_(None))
    if codes:
        stmt = stmt.where(InsiderTransaction.code.in_(codes))
    if issuer_cik is not None:
        stmt = stmt.where(InsiderTransaction.issuer_cik == issuer_cik)
    rows, next_cursor = paginate(session, stmt, TRANSACTION_KEYS, cursor, limit)
    txs = [row[0] for row in rows]
    filings = {
        filing.accession_no: filing
        for filing in session.execute(
            select(Filing).where(Filing.accession_no.in_({tx.accession_no for tx in txs}))
        ).scalars()
    }
    items = [_transaction_out(session, tx, filings[tx.accession_no], cik) for tx in txs]
    return TransactionPage(items=items, next_cursor=next_cursor)


# --------------------------------------------------------------------------- performance
def performance_out(curve) -> PerformanceOut:
    return PerformanceOut(
        basis=curve.basis,
        points=curve_points(curve.points),
        windows=[window_stat(w) for w in ordered_windows(curve.windows)],
        coverage_pct=curve.coverage_pct,
        as_of=curve.as_of,
    )


# --------------------------------------------------------------------------- holdings
def get_holdings(session: Session, cik: int) -> HoldingsOut:
    positions = list(session.execute(select(Position).where(Position.owner_cik == cik)).scalars())
    ciks = {p.issuer_cik for p in positions}
    symbols = current_symbols(session, ciks)
    issuers = issuer_refs(session, ciks)
    sectors = {
        row.cik: row.sector
        for row in session.execute(select(Issuer.cik, Issuer.sector).where(Issuer.cik.in_(ciks)))
    }
    closes = {c: latest_close(session, symbols[c]) for c in ciks if c in symbols}

    values: list[float | None] = []
    by_issuer_value: dict[int, float] = {}
    for p in positions:
        close = closes.get(p.issuer_cik)
        value = p.shares * close[0] if (close is not None and p.shares is not None) else None
        values.append(value)
        if value is not None:
            by_issuer_value[p.issuer_cik] = by_issuer_value.get(p.issuer_cik, 0.0) + value

    total = sum(by_issuer_value.values())
    positions_out = [
        HoldingOut(
            issuer=issuers[p.issuer_cik],
            security_title=p.security_title,
            shares=p.shares,
            value_usd=value,
            weight=(value / total) if (value is not None and total) else None,
            sector=sectors.get(p.issuer_cik),
            direct_indirect=p.direct_indirect,
            as_of_date=p.as_of_date,
        )
        for p, value in zip(positions, values, strict=True)
    ]

    by_issuer_label = {str(cik): issuers[cik].name for cik in by_issuer_value}
    by_issuer = [
        AllocationSlice.model_validate(s)
        for s in allocation_slices(
            {str(cik): v for cik, v in by_issuer_value.items()}, by_issuer_label
        )
    ]
    by_sector_value: dict[str, float] = {}
    for cik, value in by_issuer_value.items():
        key = sectors.get(cik) or "Unknown"
        by_sector_value[key] = by_sector_value.get(key, 0.0) + value
    by_sector = [AllocationSlice.model_validate(s) for s in allocation_slices(by_sector_value)]

    weights = [v / total for v in by_issuer_value.values()] if total else []
    derivatives = _derivative_holdings(session, cik, issuers)

    return HoldingsOut(
        positions=positions_out,
        derivatives=derivatives,
        by_sector=by_sector,
        by_issuer=by_issuer,
        effective_n=effective_n(weights),
        top5_weight=top5_weight(weights),
        total_value_usd=total,
    )


def _derivative_holdings(session: Session, cik: int, issuers: dict) -> list[HoldingOut]:
    rows = list(
        session.execute(
            select(InsiderHolding)
            .join(FilingOwner, FilingOwner.accession_no == InsiderHolding.accession_no)
            .where(
                FilingOwner.owner_cik == cik,
                InsiderHolding.table_kind == "deriv",
                InsiderHolding.superseded_by.is_(None),
            )
        ).scalars()
    )
    missing = {r.issuer_cik for r in rows} - set(issuers)
    if missing:
        issuers = {**issuers, **issuer_refs(session, missing)}
    return [
        HoldingOut(
            issuer=issuers[row.issuer_cik],
            security_title=row.security_title,
            shares=row.shares_owned,
            value_usd=None,
            weight=None,
            sector=None,
            direct_indirect=row.direct_indirect,
            as_of_date=None,
        )
        for row in rows
    ]


# --------------------------------------------------------------------------- form 144
def list_form144(session: Session, cik: int) -> list[Form144Out]:
    rows = session.execute(
        select(Form144Notice, Filing.filed_date)
        .join(Filing, Filing.accession_no == Form144Notice.accession_no)
        .where(Form144Notice.filer_cik == cik)
        .order_by(Filing.filed_date.desc())
    ).all()
    day = today()
    out = []
    for notice, filed_date in rows:
        if notice.matched_sale_accession is not None:
            status = "matched"
        elif (
            notice.approx_sale_date is not None
            and notice.approx_sale_date + timedelta(days=90) < day
        ):
            status = "expired"
        else:
            status = "pending"
        out.append(
            Form144Out(
                accession_no=notice.accession_no,
                sec_url=sec_url(cik, notice.accession_no),
                filed_date=filed_date,
                issuer=issuer_ref(session, notice.issuer_cik or 0),
                seller_name=notice.seller_name,
                relationship=notice.relationship,
                shares_to_sell=notice.shares_to_sell,
                market_value_usd=notice.market_value_usd,
                approx_sale_date=notice.approx_sale_date,
                broker=notice.broker,
                plan_10b5_1_adopted=notice.plan_10b5_1_adopted,
                matched_sale_accession=notice.matched_sale_accession,
                status=status,  # type: ignore[arg-type]
            )
        )
    return out
