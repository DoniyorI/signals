"""Write a parsed Form 144 notice into `form144_notices` and the feed, inside the caller's
transaction. Re-normalizing is idempotent and keeps the analytics-owned sale match."""

import re
from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from signals.db.models import Filing, Form144Notice, Issuer, OwnerRole
from signals.domain.feed import FeedItemIn, upsert_feed_item
from signals.domain.owner_group import owner_group_key
from signals.domain.roles import top_role
from signals.domain.tickers import current_symbol
from signals.domain.types import PlanFlag, Role
from signals.ingest.normalize_insider import owner_type_for, upsert_issuer_name, upsert_owner
from signals.ingest.parsers.form144 import Form144Doc
from signals.sec.sgml import SgmlFiling

_RELATIONSHIP_ROLES: tuple[tuple[re.Pattern[str], Role], ...] = (
    (re.compile(r"director", re.IGNORECASE), Role.DIRECTOR),
    (re.compile(r"officer", re.IGNORECASE), Role.OTHER_OFFICER),
    (re.compile(r"10\s*%|ten\s+percent", re.IGNORECASE), Role.TEN_PCT_OWNER),
)


def form144_summary(shares: float | None, value: float | None, sale_date: date | None) -> str:
    """'Plans to sell 2,013 sh (~$257,664) around Sep 25, 2026'; unknown parts left out."""
    parts = ["Plans to sell"]
    if shares is not None:
        parts.append(f"{shares:,.0f} sh")
    if value is not None:
        parts.append(f"(~${value:,.0f})")
    if sale_date is not None:
        parts.append(f"around {sale_date:%b %d, %Y}")
    return " ".join(parts)


def _relationship_roles(relationships: Sequence[str]) -> list[Role]:
    roles = [
        role
        for text in relationships
        for pattern, role in _RELATIONSHIP_ROLES
        if pattern.search(text)
    ]
    if relationships and not roles:
        roles.append(Role.OTHER)
    return roles


def _roles(session: Session, filer_cik: int, issuer_cik: int | None, relationships: Sequence[str]):
    """Roles from the filer's Form 3/4/5 history at the issuer, else from the notice."""
    if issuer_cik is not None:
        known = session.scalar(
            select(OwnerRole.roles).where(
                OwnerRole.owner_cik == filer_cik, OwnerRole.issuer_cik == issuer_cik
            )
        )
        if known:
            return [Role(r) for r in known]
    return _relationship_roles(relationships)


def normalize_form144(session: Session, filing: Filing, doc: Form144Doc, sgml: SgmlFiling) -> None:
    acc = filing.accession_no
    subject = sgml.ciks_by_role.get("SUBJECT COMPANY") or []
    issuer_cik = doc.issuer_cik or (subject[0] if subject else None)
    filer_cik = sgml.primary_cik()
    if issuer_cik is not None:
        upsert_issuer_name(
            session, issuer_cik, doc.issuer_name or sgml.names_by_cik.get(issuer_cik)
        )
    filer_name = sgml.names_by_cik.get(filer_cik) or doc.seller_name or f"CIK {filer_cik}"
    relationships = " ".join(doc.relationships)
    upsert_owner(
        session,
        filer_cik,
        filer_name,
        owner_type_for(
            filer_name,
            is_officer=bool(re.search("officer", relationships, re.IGNORECASE)),
            is_director=bool(re.search("director", relationships, re.IGNORECASE)),
        ),
    )

    values = {
        "filer_cik": filer_cik,
        "issuer_cik": issuer_cik,
        "seller_name": doc.seller_name,
        "relationship": ", ".join(doc.relationships) or None,
        "security_class": doc.security_class,
        "broker": doc.broker,
        "shares_to_sell": doc.shares_to_sell,
        "market_value_usd": doc.market_value_usd,
        "shares_outstanding": doc.shares_outstanding,
        "approx_sale_date": doc.approx_sale_date,
        "exchange": doc.exchange,
        "acquired_how": doc.acquired_how,
        "acquired_date": doc.acquired_date,
        "plan_10b5_1_adopted": doc.plan_10b5_1_adopted,
    }
    stmt = pg_insert(Form144Notice).values(accession_no=acc, **values)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["accession_no"],  # matched_sale_accession belongs to analytics
            set_={**{k: stmt.excluded[k] for k in values}, "updated_at": func.now()},
        )
    )

    issuer = session.get(Issuer, issuer_cik) if issuer_cik is not None else None
    role = top_role(_roles(session, filer_cik, issuer_cik, doc.relationships))
    shares, value = doc.shares_to_sell, doc.market_value_usd
    upsert_feed_item(
        session,
        FeedItemIn(
            accession_no=acc,
            form_type=filing.form_type,
            accepted_at=filing.accepted_at,
            filed_date=filing.filed_date,
            issuer_cik=issuer_cik,
            issuer_name=issuer.name if issuer else doc.issuer_name,
            ticker=current_symbol(session, issuer_cik) if issuer_cik is not None else None,
            owner_group=owner_group_key([filer_cik]),
            owner_ciks=(filer_cik,),
            owner_names=filer_name,
            top_role=role.value if role else None,
            direction="sell",
            codes=("144",),
            value_usd=value,
            shares=shares,
            price=value / shares if value is not None and shares else None,
            plan_10b5_1=(PlanFlag.FLAG if doc.plan_10b5_1_adopted else PlanFlag.NONE).value,
            sector=issuer.sector if issuer else None,
            summary=form144_summary(shares, value, doc.approx_sale_date),
        ),
    )
    session.flush()
