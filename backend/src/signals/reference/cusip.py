"""CUSIP to ticker mapping: OpenFIGI first, then a fuzzy match on the issuer name.

Coverage (the share of 13F value mapped to a priced ticker) is a Data health metric (spec 7.7),
so every attempt records an outcome on `securities` — mapped, name-matched, or `unresolved` —
never left silently unresolved.
"""

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from rapidfuzz import fuzz
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session

from signals.db.models import FundPosition, Issuer, Security
from signals.domain.tickers import canonical_symbol, current_symbol, issuer_for_symbol

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
MAX_RETRIES = 5
BATCH_WITH_KEY = 100
BATCH_WITHOUT_KEY = 10
SPACING_WITH_KEY = 0.24
SPACING_WITHOUT_KEY = 2.4

_DROP_TOKENS = {
    "INC",
    "INCORPORATED",
    "CORP",
    "CORPORATION",
    "CO",
    "COMPANY",
    "LTD",
    "LIMITED",
    "PLC",
    "LLC",
    "LP",
    "HOLDINGS",
    "HLDGS",
    "GROUP",
    "THE",
    "NEW",
    "CL",
    "CLASS",
    "COM",
    "SA",
    "NV",
    "AG",
}
_PUNCTUATION = re.compile(r"[^\w\s]")
_MATCH_THRESHOLD = 92


@dataclass(frozen=True)
class FigiMatch:
    ticker: str
    exch_code: str
    figi: str
    security_type: str | None
    name: str | None
    market_sector: str | None


@dataclass(frozen=True)
class MapResult:
    requested: int
    mapped_openfigi: int
    mapped_name: int
    unresolved: int


def choose_listing(candidates: list[dict]) -> FigiMatch | None:
    """Prefer `marketSector == "Equity"`, then `exchCode == "US"`; the first match wins."""
    if not candidates:
        return None
    equity = [c for c in candidates if c.get("marketSector") == "Equity"]
    pool = equity or candidates
    us = [c for c in pool if c.get("exchCode") == "US"]
    chosen = (us or pool)[0]
    ticker = canonical_symbol(chosen.get("ticker"))
    if ticker is None:
        return None
    return FigiMatch(
        ticker=ticker,
        exch_code=chosen.get("exchCode") or "",
        figi=chosen["figi"],
        security_type=chosen.get("securityType"),
        name=chosen.get("name"),
        market_sector=chosen.get("marketSector"),
    )


class OpenFigiClient:
    """POSTs batches of CUSIPs to OpenFIGI's mapping endpoint.

    Batch size and the minimum spacing between requests both depend on whether an API key is
    set (100 jobs / 0.24s with a key, 10 jobs / 2.4s without). A 429 sleeps
    `ratelimit-reset` seconds and retries, up to `MAX_RETRIES` attempts total.
    """

    def __init__(
        self,
        http: httpx.Client,
        api_key: str | None,
        *,
        sleep=time.sleep,
        clock=time.monotonic,
    ) -> None:
        self.http = http
        self.api_key = api_key
        self._sleep = sleep
        self._clock = clock

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-OPENFIGI-APIKEY"] = self.api_key
        return headers

    def _post(self, batch: Sequence[str]) -> list[dict]:
        body = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in batch]
        headers = self._headers()
        response: httpx.Response | None = None
        for _attempt in range(MAX_RETRIES):
            response = self.http.post(OPENFIGI_URL, json=body, headers=headers)
            if response.status_code == 429:
                wait = int(response.headers.get("ratelimit-reset", "60"))
                self._sleep(wait)
                continue
            response.raise_for_status()
            return response.json()
        assert response is not None
        response.raise_for_status()
        return response.json()

    def map_cusips(self, cusips: Sequence[str]) -> dict[str, FigiMatch | None]:
        batch_size = BATCH_WITH_KEY if self.api_key else BATCH_WITHOUT_KEY
        spacing = SPACING_WITH_KEY if self.api_key else SPACING_WITHOUT_KEY
        results: dict[str, FigiMatch | None] = {}
        last_request_at: float | None = None
        for start in range(0, len(cusips), batch_size):
            batch = list(cusips[start : start + batch_size])
            if last_request_at is not None:
                wait = spacing - (self._clock() - last_request_at)
                if wait > 0:
                    self._sleep(wait)
            items = self._post(batch)
            last_request_at = self._clock()
            for cusip, item in zip(batch, items, strict=True):
                results[cusip] = (
                    None if "warning" in item else choose_listing(item.get("data") or [])
                )
        return results


def _normalize_name(name: str) -> str:
    cleaned = _PUNCTUATION.sub(" ", name.upper())
    tokens = [t for t in cleaned.split() if t and t not in _DROP_TOKENS]
    return " ".join(tokens)


def name_match_issuer(session: Session, name_of_issuer: str) -> int | None:
    """Fuzzy-match a 13F `nameOfIssuer` string to an `issuers` row.

    Candidates are narrowed by the normalized query's first token against the raw issuer name
    (there is no normalized column to index), then the best `token_sort_ratio` on both names
    normalized the same way wins, if it clears the threshold.
    """
    normalized = _normalize_name(name_of_issuer)
    if not normalized:
        return None
    first_token = normalized.split()[0]
    candidates = session.execute(
        select(Issuer.cik, Issuer.name).where(Issuer.name.ilike(f"{first_token}%"))
    ).all()
    best_cik: int | None = None
    best_score = 0.0
    for cik, name in candidates:
        score = fuzz.token_sort_ratio(normalized, _normalize_name(name))
        if score > best_score:
            best_cik, best_score = cik, score
    return best_cik if best_score >= _MATCH_THRESHOLD else None


def _upsert_security(session: Session, cusip: str, **values: object) -> None:
    stmt = insert(Security).values(cusip=cusip, **values)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Security.cusip],
            set_={**{k: stmt.excluded[k] for k in values}, "updated_at": func.now()},
        )
    )


def map_securities(
    session: Session, figi: OpenFigiClient, *, limit: int | None = None
) -> MapResult:
    """Resolve distinct effective `fund_positions.cusip` values with no `securities` row, or
    whose `map_status='pending'`: OpenFIGI first, then a name match, else `unresolved`."""
    session.flush()
    query = (
        select(FundPosition.cusip, FundPosition.name_of_issuer)
        .ext(distinct_on(FundPosition.cusip))
        .outerjoin(Security, Security.cusip == FundPosition.cusip)
        .where(
            FundPosition.is_effective,
            or_(Security.cusip.is_(None), Security.map_status == "pending"),
        )
        .order_by(FundPosition.cusip)
    )
    if limit is not None:
        query = query.limit(limit)
    rows = session.execute(query).all()
    if not rows:
        return MapResult(requested=0, mapped_openfigi=0, mapped_name=0, unresolved=0)

    cusips = [row.cusip for row in rows]
    name_by_cusip = {row.cusip: row.name_of_issuer for row in rows}
    matches = figi.map_cusips(cusips)

    mapped_openfigi = mapped_name = unresolved = 0
    for cusip in cusips:
        match = matches.get(cusip)
        if match is not None:
            _upsert_security(
                session,
                cusip,
                ticker=match.ticker,
                figi=match.figi,
                security_type=match.security_type,
                name=match.name,
                issuer_cik=issuer_for_symbol(session, match.ticker),
                map_source="openfigi",
                map_status="mapped",
            )
            mapped_openfigi += 1
            continue

        issuer_cik = name_match_issuer(session, name_by_cusip.get(cusip) or "")
        if issuer_cik is not None:
            _upsert_security(
                session,
                cusip,
                ticker=current_symbol(session, issuer_cik),
                figi=None,
                security_type=None,
                name=name_by_cusip.get(cusip),
                issuer_cik=issuer_cik,
                map_source="name_match",
                map_status="mapped",
            )
            mapped_name += 1
            continue

        _upsert_security(
            session,
            cusip,
            ticker=None,
            figi=None,
            security_type=None,
            name=name_by_cusip.get(cusip),
            issuer_cik=None,
            map_source="none",
            map_status="unresolved",
        )
        unresolved += 1

    session.flush()
    return MapResult(
        requested=len(cusips),
        mapped_openfigi=mapped_openfigi,
        mapped_name=mapped_name,
        unresolved=unresolved,
    )
