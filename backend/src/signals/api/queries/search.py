"""Queries behind `GET /search`.

Three independent groups (companies, insiders, funds), each ranked by a pg_trgm similarity
score against the entity's name, with an exact ticker or CIK match forced to score 1.0. The
plan only spells out the >0.2 similarity cutoff for companies; the same cutoff (and a
case-insensitive comparison, needed for e.g. `q=doe` to find "Doe Jane") is applied to
insiders and funds too, for consistent behavior across all three kinds and because it uses
the trigram GIN indexes the foundation migration already created on all three name columns.
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signals.api.queries.common import current_symbols
from signals.api.schemas import SearchHit, SearchOut
from signals.db.models import FundManager, Issuer, Owner, OwnerRole
from signals.domain.tickers import canonical_symbol, current_symbol, issuer_for_symbol
from signals.domain.types import ROLE_PRIORITY

SIMILARITY_THRESHOLD = 0.2


def _rank(scores: dict[int, float], limit: int) -> list[tuple[int, float]]:
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]


def _search_companies(session: Session, q: str, limit: int) -> list[SearchHit]:
    scores: dict[int, float] = {}
    canonical = canonical_symbol(q)
    if canonical:
        cik = issuer_for_symbol(session, canonical)
        if cik is not None:
            scores[cik] = 1.0
    if q.isdigit() and session.get(Issuer, int(q)) is not None:
        scores[int(q)] = max(scores.get(int(q), 0.0), 1.0)
    q_lower = q.lower()
    for cik, score in session.execute(
        select(Issuer.cik, func.similarity(func.lower(Issuer.name), q_lower)).where(
            func.similarity(func.lower(Issuer.name), q_lower) > SIMILARITY_THRESHOLD
        )
    ).all():
        scores[cik] = max(scores.get(cik, 0.0), float(score))

    top = _rank(scores, limit)
    ciks = [cik for cik, _ in top]
    issuers = {
        i.cik: i for i in session.execute(select(Issuer).where(Issuer.cik.in_(ciks))).scalars()
    }
    symbols = current_symbols(session, ciks)
    hits = []
    for cik, score in top:
        issuer = issuers.get(cik)
        ticker = symbols.get(cik)
        sector = issuer.sector if issuer else None
        hits.append(
            SearchHit(
                kind="company",
                cik=cik,
                name=issuer.name if issuer else f"CIK {cik}",
                ticker=ticker,
                subtitle=f"{ticker or '—'} · {sector or 'Unknown'}",
                score=score,
            )
        )
    return hits


def _top_role_and_ticker(session: Session, cik: int) -> tuple[str | None, str | None]:
    roles = list(session.execute(select(OwnerRole).where(OwnerRole.owner_cik == cik)).scalars())
    if not roles:
        return None, None
    all_roles = {r for row in roles for r in (row.roles or [])}
    top_role = next((role.value for role in ROLE_PRIORITY if role.value in all_roles), None)
    latest = max(roles, key=lambda r: r.last_filed or date.min)
    ticker = current_symbol(session, latest.issuer_cik)
    return top_role, ticker


def _search_insiders(session: Session, q: str, limit: int) -> list[SearchHit]:
    scores: dict[int, float] = {}
    if q.isdigit() and session.get(Owner, int(q)) is not None:
        scores[int(q)] = 1.0
    q_lower = q.lower()
    for cik, score in session.execute(
        select(Owner.cik, func.similarity(func.lower(Owner.name), q_lower)).where(
            func.similarity(func.lower(Owner.name), q_lower) > SIMILARITY_THRESHOLD
        )
    ).all():
        scores[cik] = max(scores.get(cik, 0.0), float(score))

    top = _rank(scores, limit)
    owners = {
        o.cik: o
        for o in session.execute(
            select(Owner).where(Owner.cik.in_([cik for cik, _ in top]))
        ).scalars()
    }
    hits = []
    for cik, score in top:
        owner = owners.get(cik)
        top_role, ticker = _top_role_and_ticker(session, cik)
        subtitle = " · ".join(part for part in (top_role, ticker) if part) or None
        hits.append(
            SearchHit(
                kind="insider",
                cik=cik,
                name=owner.name if owner else f"CIK {cik}",
                ticker=None,
                subtitle=subtitle,
                score=score,
            )
        )
    return hits


def _search_funds(session: Session, q: str, limit: int) -> list[SearchHit]:
    scores: dict[int, float] = {}
    if q.isdigit() and session.get(FundManager, int(q)) is not None:
        scores[int(q)] = 1.0
    q_lower = q.lower()
    for cik, score in session.execute(
        select(FundManager.cik, func.similarity(func.lower(FundManager.name), q_lower)).where(
            func.similarity(func.lower(FundManager.name), q_lower) > SIMILARITY_THRESHOLD
        )
    ).all():
        scores[cik] = max(scores.get(cik, 0.0), float(score))

    top = _rank(scores, limit)
    managers = {
        m.cik: m
        for m in session.execute(
            select(FundManager).where(FundManager.cik.in_([cik for cik, _ in top]))
        ).scalars()
    }
    hits = []
    for cik, score in top:
        manager = managers.get(cik)
        aum = manager.latest_value_usd if manager else None
        subtitle = f"13F · ${aum / 1e9:.1f}B" if aum else "13F"
        hits.append(
            SearchHit(
                kind="fund",
                cik=cik,
                name=manager.name if manager else f"CIK {cik}",
                ticker=None,
                subtitle=subtitle,
                score=score,
            )
        )
    return hits


def search(session: Session, q: str, *, limit: int) -> SearchOut:
    return SearchOut(
        insiders=_search_insiders(session, q, limit),
        companies=_search_companies(session, q, limit),
        funds=_search_funds(session, q, limit),
    )
