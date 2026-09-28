"""Company reference data from SEC bulk files (spec 7.4 step 1 and 7.7).

`submissions.zip` holds one JSON per CIK (`CIK##########.json`, whose `filings.recent`
holds column arrays) plus overflow pages of older filings
(`CIK##########-submissions-###.json`, column arrays at the top level). It fills `issuers`,
ticker evidence and `filing_acceptance` (the SEC acceptance time of every tracked filing,
used for bulk-loaded filings whose `.txt` header was never fetched).

Only the first valid ticker SEC lists for a CIK is recorded as evidence. `rebuild_tickers`
models one symbol per issuer at a time, so recording every class (a preferred `CCNEP`, a
warrant or a unit next to the common) would make the later-seen class the "current" ticker.
"""

import json
import re
import zipfile
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

from sqlalchemy import Table, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from signals.db.models import FilingAcceptance, Issuer
from signals.domain.accession import normalize_accession
from signals.domain.calendars import ET, now_et
from signals.domain.tickers import canonical_symbol, rebuild_tickers, record_ticker_evidence
from signals.domain.types import TRACKED_FORMS
from signals.logging import get_logger

log = get_logger(__name__)

_MAIN_MEMBER = re.compile(r"^CIK(\d{10})\.json$")
_PAGE_MEMBER = re.compile(r"^CIK(\d{10})-submissions-\d+\.json$")
_REBUILD_CHUNK = 5000


@dataclass(frozen=True)
class SubmissionFiling:
    accession_no: str
    form: str
    filing_date: date
    acceptance: datetime | None


@dataclass(frozen=True)
class SubmissionsRecord:
    cik: int
    name: str
    entity_type: str | None
    sic: int | None
    sic_description: str | None
    tickers: tuple[str, ...]
    exchanges: tuple[str, ...]
    state_of_inc: str | None
    fiscal_year_end: str | None
    filings: tuple[SubmissionFiling, ...]


@dataclass(frozen=True)
class SubmissionsResult:
    entities: int
    issuers: int
    acceptances: int
    errors: int = 0


def parse_acceptance_datetime(raw: str) -> datetime:
    """Parse `acceptanceDateTime` into a tz-aware datetime in ET.

    Checked against the SGML header: the trailing Z is true UTC (13:18:52Z == 09:18:52 EDT).
    """
    value = datetime.fromisoformat(raw.strip())
    if value.tzinfo is None:
        raise ValueError(f"acceptanceDateTime has no timezone: {raw!r}")
    return value.astimezone(ET)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).replace("\x00", "").strip()
    return cleaned or None


def _texts(values: Iterable[Any] | None) -> tuple[str, ...]:
    return tuple(t for t in (_text(v) for v in values or ()) if t)


def _sic(value: Any) -> int | None:
    text = _text(value)
    return int(text) if text and text.isdigit() else None


def _filings(columns: Mapping[str, Any]) -> tuple[SubmissionFiling, ...]:
    """Rows from EDGAR's column arrays; unequal column lengths raise ValueError."""
    out: list[SubmissionFiling] = []
    for accession, form, filed, accepted in zip(
        columns.get("accessionNumber") or [],
        columns.get("form") or [],
        columns.get("filingDate") or [],
        columns.get("acceptanceDateTime") or [],
        strict=True,
    ):
        raw_accepted = _text(accepted)
        out.append(
            SubmissionFiling(
                accession_no=normalize_accession(str(accession)),
                form=_text(form) or "",
                filing_date=date.fromisoformat(str(filed).strip()),
                acceptance=parse_acceptance_datetime(raw_accepted) if raw_accepted else None,
            )
        )
    return tuple(out)


def parse_submissions_json(data: bytes) -> SubmissionsRecord:
    """A main per-CIK file: entity facts plus `filings.recent`."""
    doc = json.loads(data)
    filings = doc.get("filings") or {}
    return SubmissionsRecord(
        cik=int(doc["cik"]),
        name=_text(doc.get("name")) or "",
        entity_type=_text(doc.get("entityType")),
        sic=_sic(doc.get("sic")),
        sic_description=_text(doc.get("sicDescription")),
        tickers=_texts(doc.get("tickers")),
        exchanges=_texts(doc.get("exchanges")),
        state_of_inc=_text(doc.get("stateOfIncorporation")),
        fiscal_year_end=_text(doc.get("fiscalYearEnd")),
        filings=_filings(filings.get("recent") or {}),
    )


def parse_submissions_page(data: bytes) -> tuple[SubmissionFiling, ...]:
    """An overflow file of older filings: column arrays at the top level."""
    return _filings(json.loads(data))


def _upsert_issuer(session: Session, rec: SubmissionsRecord) -> None:
    values = {
        "name": rec.name,
        "sic": rec.sic,
        "sic_description": rec.sic_description,
        "exchange": rec.exchanges[0] if rec.exchanges else None,
        "state_of_inc": rec.state_of_inc,
        "fiscal_year_end": rec.fiscal_year_end,
    }
    stmt = insert(Issuer).values(cik=rec.cik, **values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Issuer.cik], set_={**values, "updated_at": func.now()}
    )
    session.execute(stmt)


def _primary_symbol(tickers: Sequence[str]) -> str | None:
    """SEC lists a CIK's primary class first; skip entries that are not valid symbols."""
    return next((t for t in tickers if canonical_symbol(t)), None)


def _upsert_issuer_from_tickers(
    session: Session, cik: int, name: str, exchange: str | None
) -> None:
    """Like `_upsert_issuer`, but only ever sets `exchange`: the name comes from
    `submissions.zip` (fuller data), so an issuer already known keeps its existing name."""
    stmt = insert(Issuer).values(cik=cik, name=name, exchange=exchange)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Issuer.cik],
        set_={"exchange": stmt.excluded.exchange, "updated_at": func.now()},
    )
    session.execute(stmt)


def _insert_acceptances(
    session: Session, cik: int, filings: Sequence[SubmissionFiling], forms: Collection[str]
) -> int:
    rows = [
        {
            "accession_no": f.accession_no,
            "cik": cik,
            "form_type": f.form,
            "filing_date": f.filing_date,
            "accepted_at": f.acceptance,
        }
        for f in filings
        if f.form in forms and f.acceptance is not None
    ]
    if not rows:
        return 0
    table = cast(Table, FilingAcceptance.__table__)
    stmt = insert(table).on_conflict_do_nothing(index_elements=[table.c.accession_no])
    return len(session.execute(stmt.returning(table.c.accession_no), rows).all())


def _rebuild_in_chunks(session: Session, issuer_ciks: Collection[int]) -> None:
    ordered = sorted(issuer_ciks)
    for i in range(0, len(ordered), _REBUILD_CHUNK):
        rebuild_tickers(session, ordered[i : i + _REBUILD_CHUNK])


def _parse_member(
    name: str, data: bytes
) -> tuple[SubmissionsRecord | None, int, tuple[SubmissionFiling, ...]]:
    """(record for a main file, the CIK, its filings). Overflow pages carry no entity."""
    page = _PAGE_MEMBER.match(name)
    if page is not None:
        return None, int(page.group(1)), parse_submissions_page(data)
    record = parse_submissions_json(data)
    return record, record.cik, record.filings


def load_submissions_zip(
    session: Session,
    zip_path: Path,
    *,
    forms: frozenset[str] = TRACKED_FORMS,
    batch_size: int = 5000,
    seen_on: date | None = None,
) -> SubmissionsResult:
    """Stream the members of submissions.zip (never extracting the archive) into the DB.

    Issuers are upserted only for entities with a SIC code or a ticker. Acceptance rows
    are inserted once per accession (a filing appears under every CIK it names). A member
    that fails to parse is logged, counted in `errors` and skipped. Commits every
    `batch_size` members, then rebuilds tickers for the issuers it touched.
    """
    seen_on = seen_on or now_et().date()
    entities = issuers = acceptances = errors = 0
    touched: set[int] = set()
    with zipfile.ZipFile(zip_path) as zf:
        for position, info in enumerate(zf.infolist(), start=1):
            if position % batch_size == 0:
                session.commit()
            name = PurePosixPath(info.filename).name
            if not (_MAIN_MEMBER.match(name) or _PAGE_MEMBER.match(name)):
                continue
            try:
                record, cik, filings = _parse_member(name, zf.read(info))
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                errors += 1
                log.warning("submissions_member_error", member=name, error=str(exc))
                continue
            if record is not None:
                entities += 1
                if record.sic is not None or record.tickers:
                    _upsert_issuer(session, record)
                    issuers += 1
                    symbol = _primary_symbol(record.tickers)
                    if symbol is not None:
                        record_ticker_evidence(session, cik, symbol, seen_on, "submissions")
                        touched.add(cik)
            acceptances += _insert_acceptances(session, cik, filings, forms)
    _rebuild_in_chunks(session, touched)
    session.commit()
    log.info(
        "submissions_loaded",
        entities=entities,
        issuers=issuers,
        acceptances=acceptances,
        errors=errors,
    )
    return SubmissionsResult(
        entities=entities, issuers=issuers, acceptances=acceptances, errors=errors
    )


def load_company_tickers_exchange(session: Session, data: bytes, *, seen_on: date) -> int:
    """The current SEC ticker list (`company_tickers_exchange.json`): one row per ticker
    class, `{"fields": ["cik","name","ticker","exchange"], "data": [[...], ...]}`.

    Unlike `submissions.zip`'s per-CIK record, this file has no single "tickers" list to
    pick a primary from -- a CIK's rows (for example CNB Financial's CCNE then CCNEP) are
    scattered across the array. So rows are grouped by CIK first (order preserved), then
    the same primary-ticker rule as `load_submissions_zip` applies: only the first row
    whose ticker is a valid symbol gets recorded as evidence, using the *first* row's name
    (existing issuers keep their name) and exchange -- rebuild_tickers models one symbol
    per issuer at a time, so a later-seen class would otherwise become the "current" one.
    Returns the number of rows read (not the number of distinct issuers).
    """
    doc = json.loads(data)
    col = {name: i for i, name in enumerate(doc["fields"])}
    rows: list[list[Any]] = doc.get("data") or []
    order: list[int] = []
    names: dict[int, str] = {}
    exchanges: dict[int, str | None] = {}
    tickers_by_cik: dict[int, list[str]] = {}
    for row in rows:
        cik = int(row[col["cik"]])
        if cik not in names:
            order.append(cik)
            names[cik] = _text(row[col["name"]]) or ""
            exchanges[cik] = _text(row[col["exchange"]])
        tickers_by_cik.setdefault(cik, []).append(row[col["ticker"]])
    touched: set[int] = set()
    for cik in order:
        _upsert_issuer_from_tickers(session, cik, names[cik], exchanges[cik])
        symbol = _primary_symbol(tickers_by_cik[cik])
        if symbol is not None:
            record_ticker_evidence(session, cik, symbol, seen_on, "company_tickers")
            touched.add(cik)
    _rebuild_in_chunks(session, touched)
    log.info("company_tickers_loaded", rows=len(rows), issuers=len(order))
    return len(rows)
