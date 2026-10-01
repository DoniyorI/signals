"""SEC daily/full form indexes: parsing and the nightly reconcile against `filings`.

Index rows are fixed-width but not at a fixed column: the form type can itself contain a
single space ("SCHEDULE 13D", "1-A POS"), so rows are parsed right-anchored (file name,
date, CIK peeled off the end) rather than split on the first whitespace run.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from signals.config import Settings
from signals.db.session import session_scope
from signals.domain.calendars import is_sec_business_day
from signals.domain.types import TRACKED_FORMS
from signals.ingest.amendments import relink_orphans
from signals.ingest.pipeline import ingest_accession
from signals.jobs import track_run
from signals.logging import get_logger
from signals.sec.archive import RawArchive
from signals.sec.client import SecClient

log = get_logger(__name__)

# head = form_type + company (split later); cik/date/filename are the last 3 tokens.
_TAIL = re.compile(
    r"^(?P<head>.*\S)\s+(?P<cik>\d+)\s+(?P<date>\d{4}-\d{2}-\d{2}|\d{8})\s+(?P<filename>\S+)\s*$"
)
_GAP = re.compile(r"\s{2,}")


@dataclass(frozen=True)
class IndexEntry:
    form_type: str
    company: str
    cik: int
    date_filed: date
    filename: str
    accession_no: str


@dataclass(frozen=True)
class ReconcileResult:
    day: date
    listed: int
    missing: int
    ingested: int
    errors: int


def daily_index_url(day: date) -> str:
    quarter = (day.month - 1) // 3 + 1
    return f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{quarter}/form.{day:%Y%m%d}.idx"


def full_index_url(year: int, quarter: int) -> str:
    return f"https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx"


def _parse_idx_date(text: str) -> date:
    return datetime.strptime(text, "%Y%m%d").date() if text.isdigit() else date.fromisoformat(text)


def _split_form_company(head: str) -> tuple[str, str]:
    """Form type ends at the first run of 2+ spaces; the rest is the company name."""
    match = _GAP.search(head)
    if not match:
        return head.strip(), ""
    return head[: match.start()].strip(), head[match.end() :].strip()


def parse_form_idx(text: str) -> list[IndexEntry]:
    lines = text.splitlines()
    dash = next((i for i, line in enumerate(lines) if line.startswith("---")), None)
    if dash is None:
        return []
    entries: list[IndexEntry] = []
    for line in lines[dash + 1 :]:
        stripped = line.rstrip()
        if not stripped:
            continue
        match = _TAIL.match(stripped)
        if not match:
            log.warning("index_row_unparseable", line=stripped[:120])
            continue
        form_type, company = _split_form_company(match.group("head"))
        filename = match.group("filename")
        entries.append(
            IndexEntry(
                form_type=form_type,
                company=company,
                cik=int(match.group("cik")),
                date_filed=_parse_idx_date(match.group("date")),
                filename=filename,
                accession_no=Path(filename).stem,
            )
        )
    return entries


def reconcile_day(
    client: SecClient,
    session_factory: Callable[[], Session],
    day: date,
    *,
    settings: Settings,
    archive: RawArchive,
    forms: frozenset[str] = TRACKED_FORMS,
) -> ReconcileResult:
    with track_run(session_factory, "reconcile_daily") as tracker:
        if not is_sec_business_day(day):
            return ReconcileResult(day=day, listed=0, missing=0, ingested=0, errors=0)

        # SEC may not have published a business day's index yet. Propagate the
        # failure and retain the reconcile checkpoint rather than skipping the day.
        body = client.get(daily_index_url(day))

        archive.put("daily_index", f"{day:%Y%m%d}", body, "idx")
        entries = [
            e
            for e in parse_form_idx(body.decode("utf-8", errors="replace"))
            if e.form_type in forms
        ]
        tracker.fetched = len(entries)

        missing = 0
        ingested = 0
        errors = 0
        for entry in entries:
            with session_scope(session_factory) as s:
                try:
                    outcome = ingest_accession(
                        client,
                        s,
                        cik=entry.cik,
                        accession=entry.accession_no,
                        source="daily_index",
                        settings=settings,
                        archive=archive,
                    )
                except Exception as exc:
                    errors += 1
                    missing += 1
                    log.warning(
                        "reconcile_fetch_error", accession=entry.accession_no, error=str(exc)
                    )
                    continue
            if outcome.status == "duplicate":
                continue
            missing += 1
            if outcome.status == "parsed":
                ingested += 1
            elif outcome.status == "error":
                errors += 1

        with session_scope(session_factory) as s:
            relink_orphans(s)

        tracker.new_rows = ingested
        tracker.missed = missing
        tracker.errors = errors
        return ReconcileResult(
            day=day, listed=len(entries), missing=missing, ingested=ingested, errors=errors
        )
