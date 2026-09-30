"""Queries behind `GET /feed` and `GET /feed/summary`."""

from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy import any_, select
from sqlalchemy.orm import Session

from signals.api.pagination import SortKey, paginate, parse_datetime, parse_str
from signals.api.queries.common import issuer_ref, sec_url
from signals.api.schemas import (
    ClusterEvent,
    FeedItemOut,
    FeedPage,
    FeedSummary,
    IssuerRef,
    OwnerRef,
)
from signals.db.models import Decision, FeedItem
from signals.domain.types import FUND_FORMS

FEED_KEYS = [
    SortKey("a", FeedItem.accepted_at, desc=True, nullable=True, parse=parse_datetime),
    SortKey("k", FeedItem.accession_no, desc=True, parse=parse_str),
]

# Form "families" the /feed `forms` filter accepts: each base form also covers its amendment.
_FORM_FAMILIES: dict[str, frozenset[str]] = {
    "3": frozenset({"3", "3/A"}),
    "4": frozenset({"4", "4/A"}),
    "5": frozenset({"5", "5/A"}),
    "144": frozenset({"144", "144/A"}),
    "13F": frozenset(FUND_FORMS),
    "13D": frozenset({"SCHEDULE 13D", "SCHEDULE 13D/A"}),
    "13G": frozenset({"SCHEDULE 13G", "SCHEDULE 13G/A"}),
}


def _form_types(forms: Sequence[str]) -> set[str]:
    out: set[str] = set()
    for form in forms:
        out |= _FORM_FAMILIES.get(form, {form})
    return out


def _owners(owner_ciks: list[int] | None, owner_names: str | None) -> list[OwnerRef]:
    ciks = owner_ciks or []
    names = owner_names.split("; ") if owner_names else []
    return [OwnerRef(cik=cik, name=name) for cik, name in zip(ciks, names, strict=False)]


def _feed_item_out(row: FeedItem) -> FeedItemOut:
    owner_ciks = list(row.owner_ciks or [])
    link_cik = (owner_ciks[0] if owner_ciks else None) or row.issuer_cik or 0
    issuer = (
        IssuerRef(
            cik=row.issuer_cik, name=row.issuer_name or f"CIK {row.issuer_cik}", ticker=row.ticker
        )
        if row.issuer_cik is not None
        else None
    )
    return FeedItemOut(
        accession_no=row.accession_no,
        sec_url=sec_url(link_cik, row.accession_no),
        form_type=row.form_type,
        accepted_at=row.accepted_at,
        filed_date=row.filed_date,  # type: ignore[arg-type]
        issuer=issuer,
        owners=_owners(row.owner_ciks, row.owner_names),
        top_role=row.top_role,
        direction=row.direction,  # type: ignore[arg-type]
        codes=list(row.codes or []),
        value_usd=row.value_usd,
        shares=row.shares,
        price=row.price,
        plan_10b5_1=row.plan_10b5_1,  # type: ignore[arg-type]
        badges=list(row.badges or []),
        market_cap_usd=row.market_cap_usd,
        sector=row.sector,
        summary=row.summary,
        lag_days=row.lag_days,
    )


def list_feed(
    session: Session,
    *,
    forms: Sequence[str] | None = None,
    direction: Sequence[str] | None = None,
    codes: Sequence[str] | None = None,
    roles: Sequence[str] | None = None,
    sectors: Sequence[str] | None = None,
    badges: Sequence[str] | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    min_mcap: float | None = None,
    max_mcap: float | None = None,
    include_10b5_1: bool = True,
    trade_from: date | None = None,
    trade_to: date | None = None,
    filed_from: date | None = None,
    filed_to: date | None = None,
    max_lag_days: int | None = None,
    issuer_cik: int | None = None,
    owner_cik: int | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> FeedPage:
    stmt = select(FeedItem)
    if forms:
        stmt = stmt.where(FeedItem.form_type.in_(_form_types(forms)))
    if direction:
        stmt = stmt.where(FeedItem.direction.in_(direction))
    if codes:
        stmt = stmt.where(FeedItem.codes.overlap(list(codes)))
    if roles:
        stmt = stmt.where(FeedItem.top_role.in_(roles))
    if sectors:
        stmt = stmt.where(FeedItem.sector.in_(sectors))
    if badges:
        stmt = stmt.where(FeedItem.badges.overlap(list(badges)))
    if min_value is not None:
        stmt = stmt.where(FeedItem.value_usd >= min_value)
    if max_value is not None:
        stmt = stmt.where(FeedItem.value_usd <= max_value)
    if min_mcap is not None:
        stmt = stmt.where(FeedItem.market_cap_usd >= min_mcap)
    if max_mcap is not None:
        stmt = stmt.where(FeedItem.market_cap_usd <= max_mcap)
    if not include_10b5_1:
        stmt = stmt.where(FeedItem.plan_10b5_1.is_(None) | (FeedItem.plan_10b5_1 == "none"))
    if trade_from is not None:
        stmt = stmt.where(FeedItem.first_trade_date >= trade_from)
    if trade_to is not None:
        stmt = stmt.where(FeedItem.first_trade_date <= trade_to)
    if filed_from is not None:
        stmt = stmt.where(FeedItem.filed_date >= filed_from)
    if filed_to is not None:
        stmt = stmt.where(FeedItem.filed_date <= filed_to)
    if max_lag_days is not None:
        stmt = stmt.where(FeedItem.lag_days <= max_lag_days)
    if issuer_cik is not None:
        stmt = stmt.where(FeedItem.issuer_cik == issuer_cik)
    if owner_cik is not None:
        stmt = stmt.where(any_(FeedItem.owner_ciks) == owner_cik)

    rows, next_cursor = paginate(session, stmt, FEED_KEYS, cursor, limit)
    items = [_feed_item_out(row[0]) for row in rows]
    return FeedPage(items=items, next_cursor=next_cursor)


def _clusters(session: Session, as_of: date) -> list[ClusterEvent]:
    start = as_of - timedelta(days=14)
    decisions = list(
        session.execute(
            select(Decision).where(
                Decision.badges.overlap(["cluster_buy"]),
                Decision.first_trade_date >= start,
                Decision.first_trade_date <= as_of,
            )
        ).scalars()
    )
    by_issuer: dict[int, list[Decision]] = {}
    for decision in decisions:
        by_issuer.setdefault(decision.issuer_cik, []).append(decision)
    return [
        ClusterEvent(
            issuer=issuer_ref(session, cik),
            start_date=min(d.first_trade_date for d in group),
            end_date=max(d.first_trade_date for d in group),
            owner_count=len({d.owner_group for d in group}),
            total_value_usd=sum(d.value_usd or 0.0 for d in group),
        )
        for cik, group in by_issuer.items()
    ]


def feed_summary(session: Session, as_of: date) -> FeedSummary:
    rows = list(session.execute(select(FeedItem).where(FeedItem.filed_date == as_of)).scalars())
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.form_type] = counts.get(row.form_type, 0) + 1
    buys = sorted(
        (r for r in rows if r.direction == "buy" and r.value_usd is not None),
        key=lambda r: r.value_usd,  # type: ignore[arg-type, return-value]
        reverse=True,
    )[:5]
    sells = sorted(
        (r for r in rows if r.direction == "sell" and r.value_usd is not None),
        key=lambda r: r.value_usd,  # type: ignore[arg-type, return-value]
        reverse=True,
    )[:5]
    late = [r for r in rows if "late_filing" in (r.badges or [])]
    return FeedSummary(
        date=as_of,
        counts_by_form=counts,
        top_buys=[_feed_item_out(r) for r in buys],
        top_sells=[_feed_item_out(r) for r in sells],
        clusters=_clusters(session, as_of),
        late_filings=[_feed_item_out(r) for r in late],
    )
