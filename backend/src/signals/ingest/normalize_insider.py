"""Write a parsed Form 3/4/5 into the canonical tables, inside the caller's transaction.

Writes issuers (name only when new), dated ticker evidence, owners, owner_roles,
filing_owners, insider_transactions and insider_holdings (delete-then-insert per
accession, so re-normalizing is idempotent) and the filing's feed item.

The feed-item rules live in `build_feed_item`, a pure function over row summaries, so the
bulk loader (bulk_345) derives feed items from staged rows with exactly the same rules.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from sqlalchemy import case, delete, func, insert, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from signals.db.models import (
    Filing,
    FilingOwner,
    InsiderHolding,
    InsiderTransaction,
    Issuer,
    Owner,
    OwnerRole,
)
from signals.domain.calendars import ET, sec_business_days_between
from signals.domain.feed import FeedItemIn, summarize_trade, upsert_feed_item
from signals.domain.owner_group import owner_group_key
from signals.domain.roles import normalize_roles, top_role
from signals.domain.tickers import (
    canonical_symbol,
    current_symbol,
    rebuild_tickers,
    record_ticker_evidence,
)
from signals.domain.types import CODE_LABELS, PlanFlag, Role
from signals.ingest.amendments import link_amendment, refresh_original
from signals.ingest.parsers.ownership import OwnershipDoc, OwnershipRow, ReportingOwner

# "10b5-1" (or "10b51") in footnotes or remarks. The bulk loader uses the same pattern in
# SQL, so it sticks to syntax both Python and Postgres regexes accept.
PLAN_10B5_1_PATTERN = "10b5-?1"
_PLAN_10B5_1 = re.compile(PLAN_10B5_1_PATTERN, re.IGNORECASE)

_ENTITY_NAME = re.compile(
    r"\b(INC|INCORPORATED|LLC|L\.?L\.?C|LP|L\.?P|CORP|CORPORATION|CO|COMPANY|FUND|TRUST"
    r"|HOLDINGS?|PARTNERS|CAPITAL|MANAGEMENT|GROUP|LTD|LIMITED|ADVISORS?|N\.?A)\b",
    re.IGNORECASE,
)

OwnerType = Literal["person", "entity"]


# ----------------------------------------------------------------------------- pure rules
def owner_type_for(name: str, *, is_officer: bool, is_director: bool) -> OwnerType:
    """Entities are never officers or directors and carry a corporate word in the name."""
    if not is_officer and not is_director and _ENTITY_NAME.search(name or ""):
        return "entity"
    return "person"


def classify_owner_type(owner: ReportingOwner) -> OwnerType:
    return owner_type_for(owner.name, is_officer=owner.is_officer, is_director=owner.is_director)


def mentions_10b5_1(texts: Iterable[str | None]) -> bool:
    return any(t and _PLAN_10B5_1.search(t) for t in texts)


def plan_flag_for_row(row: OwnershipRow, doc: OwnershipDoc) -> PlanFlag:
    """`flag` when the filing ticks aff10b5One; `footnote` when a footnote the row cites (or
    the remarks) mentions 10b5-1; otherwise `none`."""
    if doc.aff10b5one:
        return PlanFlag.FLAG
    cited = [doc.footnotes.get(fid) for ids in row.field_footnotes.values() for fid in ids]
    if mentions_10b5_1([*cited, doc.remarks]):
        return PlanFlag.FOOTNOTE
    return PlanFlag.NONE


@dataclass(frozen=True)
class TradeLine:
    """What the feed item needs from one transaction row."""

    table_kind: str
    code: str | None
    transaction_date: date | None
    shares: float | None
    price: float | None
    value_usd: float | None
    plan_10b5_1: str


@dataclass(frozen=True)
class OwnerLine:
    cik: int
    name: str
    roles: tuple[str, ...]


def _known_sum(values: Iterable[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return float(sum(known)) if known else None


def _vwap(lines: Sequence[TradeLine]) -> float | None:
    priced = [t for t in lines if t.shares and t.price is not None and t.price > 0]
    total = sum(t.shares or 0.0 for t in priced)
    return sum((t.shares or 0.0) * (t.price or 0.0) for t in priced) / total if total else None


def _direction(buys: Sequence[TradeLine], sells: Sequence[TradeLine]) -> str:
    """Compare the P and S sides by value (then shares, when prices are missing)."""
    if not buys and not sells:
        return "other"
    if buys and not sells:
        return "buy"
    if sells and not buys:
        return "sell"
    for measure in (lambda t: t.value_usd, lambda t: t.shares):
        b = _known_sum(measure(t) for t in buys) or 0.0
        s = _known_sum(measure(t) for t in sells) or 0.0
        if b != s:
            return "buy" if b > s else "sell"
    return "other"


def _securities(n: int) -> str:
    return f"{n} security" if n == 1 else f"{n} securities"


def build_feed_item(
    *,
    accession_no: str,
    form_type: str,
    accepted_at: datetime | None,
    filed_date: date | None,
    issuer_cik: int | None,
    issuer_name: str | None,
    ticker: str | None,
    sector: str | None,
    owners: Sequence[OwnerLine],
    trades: Sequence[TradeLine],
    n_holdings: int,
) -> FeedItemIn:
    codes = tuple(sorted({t.code for t in trades if t.code}))
    open_market = [t for t in trades if t.table_kind == "nonderiv" and t.code in ("P", "S")]
    buys = [t for t in open_market if t.code == "P"]
    sells = [t for t in open_market if t.code == "S"]
    direction = _direction(buys, sells)
    side = buys if direction == "buy" else sells if direction == "sell" else []
    shares = _known_sum(t.shares for t in side)
    value = _known_sum(t.value_usd for t in side)
    price = _vwap(side)

    plans = {t.plan_10b5_1 for t in trades}
    plan = next((p.value for p in (PlanFlag.FLAG, PlanFlag.FOOTNOTE) if p in plans), "none")
    role = top_role(Role(r) for o in owners for r in o.roles)

    trade_days = sorted(t.transaction_date for t in open_market if t.transaction_date)
    any_days = sorted(t.transaction_date for t in trades if t.transaction_date)
    first_open_market = trade_days[0] if trade_days else None
    accepted_day = accepted_at.astimezone(ET).date() if accepted_at else filed_date
    lag = (
        sec_business_days_between(first_open_market, accepted_day)
        if first_open_market and accepted_day
        else None
    )

    if direction in ("buy", "sell"):
        summary = summarize_trade(direction, shares, price, value)
    elif form_type.startswith("3"):
        summary = f"Initial holdings: {_securities(n_holdings)}"
    elif codes:
        summary = ", ".join(CODE_LABELS.get(c, c) for c in codes)
    elif n_holdings:
        summary = f"Holdings: {_securities(n_holdings)}"
    else:
        summary = "No transactions reported"

    return FeedItemIn(
        accession_no=accession_no,
        form_type=form_type,
        accepted_at=accepted_at,
        filed_date=filed_date,
        issuer_cik=issuer_cik,
        issuer_name=issuer_name,
        ticker=ticker,
        owner_group=owner_group_key(o.cik for o in owners) if owners else None,
        owner_ciks=tuple(o.cik for o in owners),
        owner_names="; ".join(o.name for o in owners) or None,
        top_role=role.value if role else None,
        direction=direction,
        codes=codes,
        value_usd=value,
        shares=shares,
        price=price,
        plan_10b5_1=plan,
        sector=sector,
        summary=summary,
        lag_days=lag,
        first_trade_date=first_open_market or (any_days[0] if any_days else None),
    )


# ----------------------------------------------------------------------------- writers
def upsert_issuer_name(session: Session, cik: int, name: str | None) -> None:
    """Create the issuer when new; reference data (names, SIC, sector) is never overwritten."""
    stmt = pg_insert(Issuer).values(cik=cik, name=name or f"CIK {cik}")
    session.execute(stmt.on_conflict_do_nothing(index_elements=["cik"]))


def upsert_owner(session: Session, cik: int, name: str, owner_type: OwnerType) -> None:
    stmt = pg_insert(Owner).values(cik=cik, name=name or f"CIK {cik}", owner_type=owner_type)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["cik"],
            set_={
                "name": stmt.excluded.name,
                "owner_type": stmt.excluded.owner_type,
                "updated_at": func.now(),
            },
            where=or_(
                Owner.name != stmt.excluded.name, Owner.owner_type != stmt.excluded.owner_type
            ),
        )
    )


def upsert_owner_role(
    session: Session,
    *,
    owner_cik: int,
    issuer_cik: int,
    is_director: bool,
    is_officer: bool,
    officer_title: str | None,
    is_ten_pct_owner: bool,
    is_other: bool,
    other_text: str | None,
    filed: date,
) -> None:
    """The newest filing (by filed date) sets the relationship; the dates span all filings."""
    roles = normalize_roles(
        officer_title,
        is_director=is_director,
        is_officer=is_officer,
        is_ten_pct_owner=is_ten_pct_owner,
        is_other=is_other,
    )
    relationship = {
        "is_director": is_director,
        "is_officer": is_officer,
        "officer_title": officer_title,
        "roles": [r.value for r in roles],
        "is_ten_pct_owner": is_ten_pct_owner,
        "is_other": is_other,
        "other_text": other_text,
    }
    stmt = pg_insert(OwnerRole).values(
        owner_cik=owner_cik,
        issuer_cik=issuer_cik,
        first_filed=filed,
        last_filed=filed,
        **relationship,
    )
    current = OwnerRole.__table__.c
    newest = or_(current.last_filed.is_(None), stmt.excluded.last_filed >= current.last_filed)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[current.owner_cik, current.issuer_cik],
            set_={
                **{k: case((newest, stmt.excluded[k]), else_=current[k]) for k in relationship},
                "first_filed": func.least(current.first_filed, stmt.excluded.first_filed),
                "last_filed": func.greatest(current.last_filed, stmt.excluded.last_filed),
                "updated_at": func.now(),
            },
        )
    )


def _unique_owners(owners: Iterable[ReportingOwner]) -> list[ReportingOwner]:
    seen: dict[int, ReportingOwner] = {}
    for owner in owners:
        seen.setdefault(owner.cik, owner)
    return list(seen.values())


def _cited_footnotes(row: OwnershipRow, doc: OwnershipDoc) -> dict[str, str]:
    cited: dict[str, str] = {}
    for ids in row.field_footnotes.values():
        for fid in ids:
            if fid in doc.footnotes:
                cited.setdefault(fid, doc.footnotes[fid])
    return cited


def normalize_ownership(session: Session, filing: Filing, doc: OwnershipDoc) -> None:
    acc = filing.accession_no
    owners = _unique_owners(doc.owners)
    if not owners:
        raise ValueError(f"{acc}: ownership document without reporting owners")

    filing.original_filed_date = doc.date_of_original_submission
    upsert_issuer_name(session, doc.issuer_cik, doc.issuer_name)
    if record_ticker_evidence(
        session, doc.issuer_cik, doc.issuer_symbol, filing.filed_date, "ownership"
    ):
        rebuild_tickers(session, [doc.issuer_cik])

    owner_lines: list[OwnerLine] = []
    for o in owners:
        upsert_owner(session, o.cik, o.name, classify_owner_type(o))
        upsert_owner_role(
            session,
            owner_cik=o.cik,
            issuer_cik=doc.issuer_cik,
            is_director=o.is_director,
            is_officer=o.is_officer,
            officer_title=o.officer_title,
            is_ten_pct_owner=o.is_ten_pct_owner,
            is_other=o.is_other,
            other_text=o.other_text,
            filed=filing.filed_date,
        )
        roles = normalize_roles(
            o.officer_title,
            is_director=o.is_director,
            is_officer=o.is_officer,
            is_ten_pct_owner=o.is_ten_pct_owner,
            is_other=o.is_other,
        )
        owner_lines.append(OwnerLine(o.cik, o.name, tuple(r.value for r in roles)))

    session.execute(delete(FilingOwner).where(FilingOwner.accession_no == acc))
    session.execute(
        insert(FilingOwner),
        [
            {
                "accession_no": acc,
                "owner_cik": o.cik,
                "is_director": o.is_director,
                "is_officer": o.is_officer,
                "officer_title": o.officer_title,
                "is_ten_pct_owner": o.is_ten_pct_owner,
                "is_other": o.is_other,
            }
            for o in owners
        ],
    )

    group = owner_group_key(o.cik for o in owners)
    session.execute(delete(InsiderTransaction).where(InsiderTransaction.accession_no == acc))
    session.execute(delete(InsiderHolding).where(InsiderHolding.accession_no == acc))
    transactions: list[dict] = []
    holdings: list[dict] = []
    trades: list[TradeLine] = []
    common_fields = (
        "table_kind",
        "row_no",
        "security_title",
        "direct_indirect",
        "nature_of_ownership",
        "exercise_price",
        "exercise_date",
        "expiration_date",
        "underlying_title",
        "underlying_shares",
    )
    for row in doc.rows:
        common = {k: getattr(row, k) for k in common_fields}
        common |= {
            "accession_no": acc,
            "issuer_cik": doc.issuer_cik,
            "owner_group": group,
            "footnotes": _cited_footnotes(row, doc),
            "superseded_by": None,
        }
        if row.row_kind == "holding":
            holdings.append(
                common
                | {"shares_owned": row.shares_owned_after, "value_owned": row.value_owned_after}
            )
            continue
        value = row.shares * row.price if row.shares is not None and row.price is not None else None
        plan = plan_flag_for_row(row, doc).value
        transactions.append(
            common
            | {
                "transaction_date": row.transaction_date,
                "deemed_execution_date": row.deemed_execution_date,
                "code": row.code,
                "form_type": row.form_type,
                "equity_swap": row.equity_swap,
                "timeliness": row.timeliness,
                "shares": row.shares,
                "price": row.price,
                "value_usd": value,
                "acquired_disposed": row.acquired_disposed,
                "shares_owned_after": row.shares_owned_after,
                "value_owned_after": row.value_owned_after,
                "plan_10b5_1": plan,
                "field_footnotes": {k: list(v) for k, v in row.field_footnotes.items()},
                "flags": ["price_missing"] if row.code in ("P", "S") and row.price is None else [],
            }
        )
        trades.append(
            TradeLine(
                row.table_kind, row.code, row.transaction_date, row.shares, row.price, value, plan
            )
        )
    if transactions:
        session.execute(insert(InsiderTransaction), transactions)
    if holdings:
        session.execute(insert(InsiderHolding), holdings)

    issuer = session.get(Issuer, doc.issuer_cik)
    upsert_feed_item(
        session,
        build_feed_item(
            accession_no=acc,
            form_type=filing.form_type,
            accepted_at=filing.accepted_at,
            filed_date=filing.filed_date,
            issuer_cik=doc.issuer_cik,
            issuer_name=issuer.name if issuer else doc.issuer_name,
            ticker=canonical_symbol(doc.issuer_symbol) or current_symbol(session, doc.issuer_cik),
            sector=issuer.sector if issuer else None,
            owners=owner_lines,
            trades=trades,
            n_holdings=len(holdings),
        ),
    )
    session.flush()
    if doc.document_type.endswith("/A"):
        link_amendment(session, acc)
    else:
        refresh_original(session, acc)
