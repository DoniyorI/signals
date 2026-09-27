"""Dated tickers. Companies are keyed by CIK; a ticker is only a lookup valid over a range.

Evidence (every sighting of a symbol for an issuer) is recorded order-independently and
`tickers` intervals are rebuilt from it. The first symbol of an issuer is backdated to
1990-01-01 so older price history resolves; when two issuers claim a symbol on a date,
the one actually seen using it on or before that date wins.
"""

import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from signals.db.models import Ticker, TickerEvidence

HISTORY_START = date(1990, 1, 1)
_VALID = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")
_JUNK = {"NONE", "N/A", "NA"}


@dataclass(frozen=True)
class TickerInterval:
    symbol: str
    valid_from: date
    valid_to: date | None


def canonical_symbol(raw: str | None) -> str | None:
    """Upper-case, no spaces, class shares in dot style (BRK-B -> BRK.B)."""
    if raw is None:
        return None
    symbol = re.sub(r"\s+", "", raw.strip().upper()).replace("-", ".")
    if not symbol or symbol in _JUNK or not _VALID.match(symbol):
        return None
    return symbol


def record_ticker_evidence(
    session: Session, issuer_cik: int, raw_symbol: str | None, seen_on: date, source: str
) -> str | None:
    symbol = canonical_symbol(raw_symbol)
    if symbol is None:
        return None
    stmt = insert(TickerEvidence).values(
        issuer_cik=issuer_cik, symbol=symbol, min_seen=seen_on, max_seen=seen_on, sources=[source]
    )
    existing = TickerEvidence.__table__.c
    stmt = stmt.on_conflict_do_update(
        index_elements=[existing.issuer_cik, existing.symbol],
        set_={
            "min_seen": func.least(existing.min_seen, stmt.excluded.min_seen),
            "max_seen": func.greatest(existing.max_seen, stmt.excluded.max_seen),
            "sources": text(
                "ARRAY(SELECT DISTINCT s FROM "
                "unnest(ticker_evidence.sources || EXCLUDED.sources) AS s ORDER BY s)"
            ),
            "updated_at": func.now(),
        },
    )
    session.execute(stmt)
    return symbol


def rebuild_tickers(session: Session, issuer_ciks: Collection[int] | None = None) -> int:
    """Replace `tickers` rows for issuers that have evidence. Returns rows written."""
    query = select(TickerEvidence).order_by(
        TickerEvidence.issuer_cik, TickerEvidence.min_seen, TickerEvidence.symbol
    )
    if issuer_ciks is not None:
        query = query.where(TickerEvidence.issuer_cik.in_(list(issuer_ciks)))
    by_issuer: dict[int, list[TickerEvidence]] = {}
    for row in session.execute(query).scalars():
        by_issuer.setdefault(row.issuer_cik, []).append(row)
    if not by_issuer:
        return 0
    session.execute(delete(Ticker).where(Ticker.issuer_cik.in_(list(by_issuer))))
    written = 0
    for cik, rows in by_issuer.items():
        for i, row in enumerate(rows):
            valid_from = HISTORY_START if i == 0 else row.min_seen
            valid_to = rows[i + 1].min_seen - timedelta(days=1) if i + 1 < len(rows) else None
            session.add(
                Ticker(
                    issuer_cik=cik,
                    symbol=row.symbol,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    source="evidence",
                )
            )
            written += 1
    session.flush()
    return written


def ticker_intervals(session: Session, issuer_cik: int) -> list[TickerInterval]:
    rows = session.execute(
        select(Ticker.symbol, Ticker.valid_from, Ticker.valid_to)
        .where(Ticker.issuer_cik == issuer_cik)
        .order_by(Ticker.valid_from)
    ).all()
    return [TickerInterval(r.symbol, r.valid_from, r.valid_to) for r in rows]


def _covers(on: date):
    return (Ticker.valid_from <= on) & or_(Ticker.valid_to.is_(None), Ticker.valid_to >= on)


def resolve_symbol(session: Session, issuer_cik: int, on: date) -> str | None:
    return session.execute(
        select(Ticker.symbol)
        .where(Ticker.issuer_cik == issuer_cik, _covers(on))
        .order_by(Ticker.valid_from.desc())
        .limit(1)
    ).scalar_one_or_none()


def current_symbol(session: Session, issuer_cik: int) -> str | None:
    return session.execute(
        select(Ticker.symbol)
        .where(Ticker.issuer_cik == issuer_cik)
        .order_by(Ticker.valid_to.desc().nulls_first(), Ticker.valid_from.desc())
        .limit(1)
    ).scalar_one_or_none()


def issuer_for_symbol(session: Session, symbol: str, on: date | None = None) -> int | None:
    canonical = canonical_symbol(symbol) or symbol
    if on is None:
        rows = session.execute(
            select(Ticker.issuer_cik, Ticker.valid_to, TickerEvidence.max_seen)
            .join(
                TickerEvidence,
                (TickerEvidence.issuer_cik == Ticker.issuer_cik)
                & (TickerEvidence.symbol == Ticker.symbol),
                isouter=True,
            )
            .where(Ticker.symbol == canonical)
            .order_by(
                Ticker.valid_to.desc().nulls_first(),
                TickerEvidence.max_seen.desc().nulls_last(),
            )
            .limit(1)
        ).first()
        return rows.issuer_cik if rows else None

    candidates = session.execute(
        select(Ticker.issuer_cik, TickerEvidence.min_seen)
        .join(
            TickerEvidence,
            (TickerEvidence.issuer_cik == Ticker.issuer_cik)
            & (TickerEvidence.symbol == Ticker.symbol),
            isouter=True,
        )
        .where(Ticker.symbol == canonical, _covers(on))
    ).all()
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0].issuer_cik
    # Prefer issuers actually seen using the symbol by `on` (latest such sighting);
    # otherwise the one whose first sighting is closest after `on`.
    seen = [c for c in candidates if c.min_seen is not None and c.min_seen <= on]
    if seen:
        return max(seen, key=lambda c: c.min_seen).issuer_cik
    later = [c for c in candidates if c.min_seen is not None]
    if later:
        return min(later, key=lambda c: c.min_seen).issuer_cik
    return candidates[0].issuer_cik
