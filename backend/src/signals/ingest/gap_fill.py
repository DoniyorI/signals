"""Resumable per-filing backfill over a date range: the quarterly full index for a past
quarter (published once the quarter closes), or daily indexes for today's quarter (the
full index for an in-progress quarter lags behind). Progress is checkpointed so a killed
run picks back up mid-quarter instead of re-walking everything already done.
"""

from collections.abc import Callable, Collection
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from signals.config import Settings
from signals.db.models import AppState
from signals.db.session import session_scope
from signals.domain.calendars import is_sec_business_day, now_et
from signals.ingest.indexes import IndexEntry, daily_index_url, full_index_url, parse_form_idx
from signals.ingest.pipeline import ingest_accession
from signals.logging import get_logger
from signals.sec.archive import RawArchive
from signals.sec.client import SecBlockedError, SecClient

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
    if (year, quarter) != _quarter_of(now_et().date()):
        # A missing index is not evidence of an empty quarter. Let the parent fail
        # visibly before any checkpoint advances, so its next request can retry it.
        body = client.get(full_index_url(year, quarter))
        archive.put("full_index", _quarter_key(year, quarter), body, "idx")
        return parse_form_idx(body.decode("utf-8", errors="replace"))

    entries: list[IndexEntry] = []
    for day in _business_days(quarter_start, end):
        body = client.get(daily_index_url(day))
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
    # Import lazily: completeness registers a worker job which calls this same scanner.
    from signals.completeness import (
        ATTEMPT_PREFIX,
        family_for,
        record_accession_failure,
        record_accession_success,
    )

    listed = 0
    ingested = 0
    skipped_existing = 0
    errors = 0
    quarters_done: list[str] = list(progress.get("quarters_done", []))
    resume = dict(progress.get("current", {}))
    pending: dict[str, list[dict]] = deepcopy(progress.get("pending_failures", {}))
    # Usually empty. Read retry metadata once, not millions of per-filing state queries
    # during a historical scan already covered by the bulk loader.
    with session_scope(session_factory) as s:
        retry_states = list(
            s.scalars(select(AppState.value).where(AppState.key.startswith(ATTEMPT_PREFIX)))
        )
    retry_tracked = {
        state["accession_no"] for state in retry_states if state.get("status") != "resolved"
    }
    unavailable = {
        state["accession_no"] for state in retry_states if state.get("status") == "unavailable"
    }
    attempted: set[str] = set()

    def attempt(cik: int, accession: str, *, form_type: str, day: date) -> dict | None:
        nonlocal listed, ingested, skipped_existing, errors
        if accession in unavailable or accession in attempted:
            return None
        # Joint filers can repeat an accession in the index, and older retry queues
        # can repeat it too. Preserve raw-row offsets while spending one attempt per run.
        attempted.add(accession)
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
                    expected_identity=(form_type, day),
                )
                if outcome.status in ("duplicate", "parsed") and accession in retry_tracked:
                    record_accession_success(s, accession)
                    retry_tracked.discard(accession)
            if outcome.status == "duplicate":
                skipped_existing += 1
                return None
            if outcome.status == "parsed":
                ingested += 1
                return None
            message = outcome.error or f"Unexpected ingest status: {outcome.status}"
        except SecBlockedError:
            # A shared SEC pause is not an accession failure and must not exhaust retries.
            raise
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            log.warning("gap_fill_fetch_error", accession=accession, error=message)
        family = family_for(form_type)
        if family is not None:
            with session_scope(session_factory) as s:
                exhausted = record_accession_failure(
                    s, accession=accession, cik=cik, family=family, day=day, error=message
                )
            retry_tracked.add(accession)
            if exhausted:
                unavailable.add(accession)
                # Terminal absence stays visible in the completeness report, while the
                # scan can finish without repeatedly blocking an entire backfill quarter.
                return None
        errors += 1
        return {
            "cik": cik,
            "accession_no": accession,
            "error": message,
            "form_type": form_type,
            "filed_date": day.isoformat(),
        }

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
        by_accession = {entry.accession_no: entry for entry in filtered}
        failures: list[dict] = []
        pending[key] = failures
        for failed in retry_entries:
            # Older checkpoints do not contain form/date metadata. Recover it from the
            # fresh index without moving their attempted offset backwards.
            entry = by_accession.get(failed["accession_no"])
            form = failed.get("form_type") or (entry.form_type if entry else next(iter(form_types)))
            day = (
                date.fromisoformat(failed["filed_date"])
                if failed.get("filed_date")
                else (entry.date_filed if entry else quarter_start)
            )
            error = attempt(failed["cik"], failed["accession_no"], form_type=form, day=day)
            if error is not None:
                failures.append(error)
        for i, entry in enumerate(filtered):
            if i < offset:
                continue
            error = attempt(
                entry.cik, entry.accession_no, form_type=entry.form_type, day=entry.date_filed
            )
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
