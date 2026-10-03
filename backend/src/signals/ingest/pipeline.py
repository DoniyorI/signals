"""Fetch -> archive -> SGML -> filings row -> handler (inside a savepoint).

Nothing here commits: callers own the transaction, so a batch can commit per filing.
A handler failure rolls back only its own writes and is recorded on the filing row.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from signals.config import Settings
from signals.db.models import Filing
from signals.domain.accession import filing_txt_url, normalize_accession
from signals.domain.calendars import now_et
from signals.ingest.dispatch import HandlerContext, get_handler
from signals.logging import get_logger
from signals.sec.archive import RawArchive
from signals.sec.client import SecClient
from signals.sec.ratelimit import Priority
from signals.sec.sgml import SgmlFiling

log = get_logger(__name__)

Status = Literal["parsed", "error", "skipped", "duplicate"]


@dataclass(frozen=True)
class IngestOutcome:
    accession_no: str
    status: Status
    error: str | None = None


def _issuer_cik(sgml: SgmlFiling) -> int | None:
    for role in ("ISSUER", "SUBJECT COMPANY"):
        ciks = sgml.ciks_by_role.get(role)
        if ciks:
            return ciks[0]
    return None


def _upsert_filing(
    session: Session,
    sgml: SgmlFiling,
    *,
    source: str,
    raw_path: str | None,
    first_seen_at: datetime | None,
) -> Filing:
    values = {
        "accession_no": sgml.accession_no,
        "form_type": sgml.form_type,
        "issuer_cik": _issuer_cik(sgml),
        "primary_cik": sgml.primary_cik(),
        "filed_date": sgml.filed_date,
        "accepted_at": sgml.accepted_at,
        "accepted_at_source": "sgml" if sgml.accepted_at else "missing",
        "period_of_report": sgml.period_of_report,
        "is_amendment": sgml.form_type.endswith("/A"),
        "source": source,
        "raw_path": raw_path,
        "parse_status": "pending",
        "parse_error": None,
        "first_seen_at": first_seen_at,
    }
    stmt = insert(Filing).values(**values)
    table = Filing.__table__.c
    stmt = stmt.on_conflict_do_update(
        index_elements=[table.accession_no],
        set_={
            **{
                k: stmt.excluded[k]
                for k in values
                if k not in ("accession_no", "source", "raw_path", "first_seen_at")
            },
            # Keep the first source and first sighting; only fill raw_path when known.
            "raw_path": func.coalesce(stmt.excluded.raw_path, table.raw_path),
            "first_seen_at": func.coalesce(table.first_seen_at, stmt.excluded.first_seen_at),
            "updated_at": func.now(),
        },
    )
    session.execute(stmt)
    filing = session.get(Filing, sgml.accession_no, populate_existing=True)
    assert filing is not None
    return filing


def ingest_raw(
    session: Session,
    raw: bytes,
    *,
    source: str,
    raw_path: str | None,
    first_seen_at: datetime | None,
    settings: Settings,
    archive: RawArchive,
    expected_identity: tuple[str, date] | None = None,
) -> IngestOutcome:
    sgml = SgmlFiling.from_txt(raw)
    if expected_identity is not None and (sgml.form_type, sgml.filed_date) != expected_identity:
        raise ValueError("Submission form/date does not match the SEC index")
    filing = _upsert_filing(
        session, sgml, source=source, raw_path=raw_path, first_seen_at=first_seen_at
    )
    handler = get_handler(sgml.form_type)
    if handler is None:
        filing.parse_status = "skipped"
        session.flush()
        return IngestOutcome(sgml.accession_no, "skipped")

    ctx = HandlerContext(settings=settings, archive=archive, source=source, now=now_et())
    try:
        with session.begin_nested():
            handler(session, sgml, filing, ctx)
    except Exception as exc:  # recorded on the filing row, surfaced by /api/health
        message = f"{type(exc).__name__}: {exc}"
        log.warning("ingest_handler_error", accession=sgml.accession_no, error=message)
        filing = session.get(Filing, sgml.accession_no, populate_existing=True)
        assert filing is not None
        filing.parse_status = "error"
        filing.parse_error = message
        # `parsed_at` is the last parse attempt, including a failed reparse.
        filing.parsed_at = now_et()
        session.flush()
        return IngestOutcome(sgml.accession_no, "error", message)

    filing.parse_status = "parsed"
    filing.parse_error = None
    filing.parsed_at = now_et()
    session.flush()
    return IngestOutcome(sgml.accession_no, "parsed")


def ingest_accession(
    client: SecClient,
    session: Session,
    *,
    cik: int,
    accession: str,
    source: str,
    priority: Priority = Priority.BULK,
    first_seen_at: datetime | None = None,
    settings: Settings,
    archive: RawArchive,
    expected_identity: tuple[str, date] | None = None,
) -> IngestOutcome:
    acc = normalize_accession(accession)
    existing = session.get(Filing, acc)
    if (
        existing is not None
        and existing.parse_status == "parsed"
        and (
            expected_identity is None
            or (existing.form_type, existing.filed_date) == expected_identity
        )
    ):
        return IngestOutcome(acc, "duplicate")
    raw = client.get(filing_txt_url(cik, acc), priority=priority)
    path = archive.put("filing", acc, raw, "txt")
    try:
        return ingest_raw(
            session,
            raw,
            source=source,
            raw_path=str(path),
            first_seen_at=first_seen_at,
            settings=settings,
            archive=archive,
            expected_identity=expected_identity,
        )
    except ValueError as exc:  # unreadable SEC wrapper: no form/date to record a row with
        log.error("ingest_unreadable_submission", accession=acc, error=str(exc))
        return IngestOutcome(acc, "error", f"{type(exc).__name__}: {exc}")


def reparse_accession(
    session: Session, accession: str, *, settings: Settings, archive: RawArchive
) -> IngestOutcome:
    """Re-run parsing from the raw archive (no network)."""
    acc = normalize_accession(accession)
    if not archive.exists("filing", acc):
        return IngestOutcome(acc, "error", f"LookupError: no raw archive for {acc}")
    existing = session.get(Filing, acc)
    return ingest_raw(
        session,
        archive.get("filing", acc),
        source=existing.source if existing else "reparse",
        raw_path=str(archive.path_for("filing", acc)),
        first_seen_at=None,
        settings=settings,
        archive=archive,
    )
