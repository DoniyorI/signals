"""Resumable per-filing backfill over a date range: the quarterly full index for a past
quarter (published once the quarter closes), or daily indexes for today's quarter (the
full index for an in-progress quarter lags behind). Progress is checkpointed so a killed
run picks back up mid-quarter instead of re-walking everything already done.
"""

from collections.abc import Callable, Collection
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from signals.config import Settings
from signals.db.session import session_scope
from signals.domain.calendars import is_sec_business_day
from signals.ingest.indexes import IndexEntry, daily_index_url, full_index_url, parse_form_idx
from signals.ingest.pipeline import ingest_accession
from signals.logging import get_logger
from signals.sec.archive import RawArchive
from signals.sec.client import SecClient, SecNotFoundError

log = get_logger(__name__)

SAVE_EVERY = 200


@dataclass(frozen=True)
class GapFillResult:
    listed: int
    ingested: int
    skipped_existing: int
    errors: int


def _quarter_of(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3 + 1


def _quarter_key(year: int, quarter: int) -> str:
    return f"{year}Q{quarter}"


def _quarter_start(year: int, quarter: int) -> date:
    return date(year, 3 * (quarter - 1) + 1, 1)


def _quarters_between(start: date, end: date) -> list[tuple[int, int]]:
    quarters: list[tuple[int, int]] = []
    year, quarter = _quarter_of(start)
    last = _quarter_of(end)
    while (year, quarter) <= last:
        quarters.append((year, quarter))
        quarter += 1
        if quarter > 4:
            quarter, year = 1, year + 1
    return quarters


def _business_days(start: date, end: date):
    day = start
    while day <= end:
        if is_sec_business_day(day):
            yield day
        day += timedelta(days=1)


def _quarter_entries(
    client: SecClient,
    archive: RawArchive,
    year: int,
    quarter: int,
    quarter_start: date,
    end: date,
) -> list[IndexEntry]:
    """The full index for a past quarter; daily indexes (the full index lags) for today's."""
    if (year, quarter) != _quarter_of(date.today()):
        try:
            body = client.get(full_index_url(year, quarter))
        except SecNotFoundError:
            return []
        archive.put("full_index", _quarter_key(year, quarter), body, "idx")
        return parse_form_idx(body.decode("utf-8", errors="replace"))

    entries: list[IndexEntry] = []
    for day in _business_days(quarter_start, end):
        try:
            body = client.get(daily_index_url(day))
        except SecNotFoundError:
            continue
        archive.put("daily_index", f"{day:%Y%m%d}", body, "idx")
        entries.extend(parse_form_idx(body.decode("utf-8", errors="replace")))
    return entries


def gap_fill(
    client: SecClient,
    session_factory: Callable[[], Session],
    *,
    form_types: Collection[str],
    start: date,
    end: date,
    settings: Settings,
    archive: RawArchive,
    progress: dict,
    save_progress: Callable[[dict], None],
    source: str = "full_index",
) -> GapFillResult:
    listed = 0
    ingested = 0
    skipped_existing = 0
    errors = 0
    quarters_done: list[str] = list(progress.get("quarters_done", []))
    resume = dict(progress.get("current", {}))
    pending: dict[str, list[dict]] = deepcopy(progress.get("pending_failures", {}))

    def attempt(cik: int, accession: str) -> dict | None:
        nonlocal listed, ingested, skipped_existing, errors
        listed += 1
        try:
            with session_scope(session_factory) as s:
                outcome = ingest_accession(
                    client,
                    s,
                    cik=cik,
                    accession=accession,
                    source=source,
                    settings=settings,
                    archive=archive,
                )
            if outcome.status == "duplicate":
                skipped_existing += 1
                return None
            if outcome.status == "parsed":
                ingested += 1
                return None
            message = outcome.error or f"Unexpected ingest status: {outcome.status}"
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            log.warning("gap_fill_fetch_error", accession=accession, error=message)
        errors += 1
        return {"cik": cik, "accession_no": accession, "error": message}

    def checkpoint(key: str, offset: int) -> None:
        progress["current"] = {"quarter": key, "offset": offset}
        progress["pending_failures"] = deepcopy(pending)
        save_progress(deepcopy(progress))

    for year, quarter in _quarters_between(start, end):
        key = _quarter_key(year, quarter)
        if key in quarters_done:
            continue

        quarter_start = max(_quarter_start(year, quarter), start)
        raw_entries = _quarter_entries(client, archive, year, quarter, quarter_start, end)
        filtered = [
            e for e in raw_entries if e.form_type in form_types and start <= e.date_filed <= end
        ]

        offset = resume.get("offset", 0) if resume.get("quarter") == key else 0
        # The attempted offset stays monotonic; a separate queue retries its failed entries.
        retry_entries = pending.pop(key, [])
        failures: list[dict] = []
        pending[key] = failures
        for failed in retry_entries:
            error = attempt(failed["cik"], failed["accession_no"])
            if error is not None:
                failures.append(error)
        for i, entry in enumerate(filtered):
            if i < offset:
                continue
            error = attempt(entry.cik, entry.accession_no)
            if error is not None:
                failures.append(error)

            # The offset must advance for every attempted entry (success or failure) so a
            # resumed scan skips entries it already accounted for. Failed entries retry
            # through pending_failures rather than moving this offset backwards.
            if (i + 1) % SAVE_EVERY == 0:
                checkpoint(key, i + 1)

        if failures:
            checkpoint(key, max(offset, len(filtered)))
            # Leave this quarter unfinished. The caller fails the parent job, so its
            # documented re-request continues from this checkpoint and retry queue.
            break

        pending.pop(key, None)
        progress["pending_failures"] = deepcopy(pending)
        quarters_done.append(key)
        progress["quarters_done"] = quarters_done
        progress.pop("current", None)
        resume = {}
        save_progress(deepcopy(progress))

    return GapFillResult(
        listed=listed, ingested=ingested, skipped_existing=skipped_existing, errors=errors
    )
