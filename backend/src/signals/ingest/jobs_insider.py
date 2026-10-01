"""Insider jobs (live poll, reconcile, backfill, weekly bulk check). Owned by workstream A."""

from dataclasses import asdict
from datetime import date, datetime, time, timedelta

from signals.db.session import run_transaction, session_scope
from signals.domain.appstate import get_state, set_state
from signals.domain.calendars import ET, is_sec_business_day
from signals.domain.types import FORM144_FORMS, INSIDER_FORMS
from signals.ingest.bulk_345 import (
    DatasetLink,
    apply_acceptance_times,
    list_345_datasets,
    load_345_zip,
)
from signals.ingest.feed import PollResult, poll_feed
from signals.ingest.gap_fill import GapFillResult, gap_fill
from signals.ingest.indexes import ReconcileResult, reconcile_day
from signals.jobs import JobContext, register_job
from signals.logging import get_logger
from signals.sec.client import Priority

log = get_logger(__name__)

LISTING_URL = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"

_WINDOW_START = time(6, 0)
_WINDOW_END = time(22, 0)

_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def _today_et(now: datetime) -> date:
    return now.astimezone(ET).date()


def _quarter_of(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3 + 1


def _quarter_end(year: int, quarter: int) -> date:
    month, day = _QUARTER_END[quarter]
    return date(year, month, day)


def _poll_result_dict(result: PollResult) -> dict:
    return {
        "pages": result.pages,
        "entries": result.entries,
        "new": result.new,
        "errors": result.errors,
        "error_details": list(result.error_details),
        "issuer_ciks": sorted(result.issuer_ciks),
        "owner_ciks": sorted(result.owner_ciks),
        "filer_ciks": sorted(result.filer_ciks),
    }


def _reconcile_result_dict(result: ReconcileResult) -> dict:
    return {**asdict(result), "day": result.day.isoformat()}


def _gap_fill_result_dict(result: GapFillResult) -> dict:
    return asdict(result)


def _fetch_listing(ctx: JobContext) -> str:
    body = ctx.sec.get(LISTING_URL, priority=Priority.BULK)
    ctx.archive.put("page", "insider_345_listing", body, "html")
    return body.decode("utf-8", errors="replace")


def _load_dataset(ctx: JobContext, ds: DatasetLink) -> None:
    zip_bytes = ctx.sec.get(ds.url, priority=Priority.BULK)
    ctx.archive.put("bulk", ds.name, zip_bytes, "zip")
    run_transaction(ctx.session_factory, lambda s: load_345_zip(s, zip_bytes, name=ds.name))


@register_job("live_poll", interval_seconds=60)
def live_poll(ctx: JobContext) -> dict:
    now = ctx.now()
    today = _today_et(now)
    now_time = now.astimezone(ET).time()
    if not (is_sec_business_day(today) and _WINDOW_START <= now_time < _WINDOW_END):
        return {"skipped": "outside window"}
    result = poll_feed(
        ctx.sec, ctx.session_factory, now=now, settings=ctx.settings, archive=ctx.archive
    )
    return _poll_result_dict(result)


@register_job("reconcile_daily", cron={"hour": 6, "minute": 30})
def reconcile_daily(ctx: JobContext) -> dict:
    yesterday = _today_et(ctx.now()) - timedelta(days=1)
    with session_scope(ctx.session_factory) as s:
        state = get_state(s, "reconcile_last_day")
    # No prior state, or a very stale one, is capped at 7 days back either way.
    last_day = date.fromisoformat(state["day"]) if state else yesterday - timedelta(days=7)
    start = max(last_day + timedelta(days=1), yesterday - timedelta(days=6))

    days: list[date] = []
    day = start
    while day <= yesterday:
        if is_sec_business_day(day):
            days.append(day)
        day += timedelta(days=1)

    results = [
        reconcile_day(ctx.sec, ctx.session_factory, d, settings=ctx.settings, archive=ctx.archive)
        for d in days
    ]
    with session_scope(ctx.session_factory) as s:
        set_state(s, "reconcile_last_day", {"day": yesterday.isoformat()})
    return {
        "days": [d.isoformat() for d in days],
        "results": [_reconcile_result_dict(r) for r in results],
    }


@register_job("backfill_insiders")
def backfill_insiders(ctx: JobContext) -> dict:
    progress = ctx.progress

    html = progress.get("listing_html")
    if html is None:
        html = _fetch_listing(ctx)
        progress["listing_html"] = html
        ctx.save_progress(progress)
    datasets = list_345_datasets(html)

    start_quarter = _quarter_of(ctx.settings.backfill_start)
    relevant = [d for d in datasets if (d.year, d.quarter) >= start_quarter]
    done = set(progress.get("datasets_done", []))
    for ds in relevant:
        if ds.name in done:
            continue
        _load_dataset(ctx, ds)
        done.add(ds.name)
        progress["datasets_done"] = sorted(done)
        ctx.save_progress(progress)

    with session_scope(ctx.session_factory) as s:
        acceptance_applied = apply_acceptance_times(s)

    yesterday = _today_et(ctx.now()) - timedelta(days=1)
    last_quarter_end = (
        max(_quarter_end(d.year, d.quarter) for d in relevant)
        if relevant
        else ctx.settings.backfill_start
    )

    insiders_progress = progress.setdefault("gap_fill_insiders", {})

    def _save_insiders(p: dict) -> None:
        progress["gap_fill_insiders"] = p
        ctx.save_progress(progress)

    gap_insiders = gap_fill(
        ctx.sec,
        ctx.session_factory,
        form_types=INSIDER_FORMS,
        start=last_quarter_end + timedelta(days=1),
        end=yesterday,
        settings=ctx.settings,
        archive=ctx.archive,
        progress=insiders_progress,
        save_progress=_save_insiders,
    )
    if gap_insiders.errors:
        raise RuntimeError(f"Insider gap fill has {gap_insiders.errors} unresolved errors")

    form144_progress = progress.setdefault("gap_fill_144", {})

    def _save_144(p: dict) -> None:
        progress["gap_fill_144"] = p
        ctx.save_progress(progress)

    gap_144 = gap_fill(
        ctx.sec,
        ctx.session_factory,
        form_types=FORM144_FORMS,
        start=ctx.settings.form144_start,
        end=yesterday,
        settings=ctx.settings,
        archive=ctx.archive,
        progress=form144_progress,
        save_progress=_save_144,
    )
    if gap_144.errors:
        raise RuntimeError(f"Form 144 gap fill has {gap_144.errors} unresolved errors")

    return {
        "datasets_loaded": len(done),
        "acceptance_applied": acceptance_applied,
        "gap_fill_insiders": _gap_fill_result_dict(gap_insiders),
        "gap_fill_144": _gap_fill_result_dict(gap_144),
    }


@register_job("bulk_check_insiders", cron={"day_of_week": "mon", "hour": 3, "minute": 0})
def bulk_check_insiders(ctx: JobContext) -> dict:
    html = _fetch_listing(ctx)
    datasets = list_345_datasets(html)

    with session_scope(ctx.session_factory) as s:
        state = get_state(s, "bulk_345_loaded")
    loaded = set((state or {}).get("names", []))

    newly_loaded = []
    for ds in datasets:
        if ds.name in loaded:
            continue
        _load_dataset(ctx, ds)
        loaded.add(ds.name)
        newly_loaded.append(ds.name)
        with session_scope(ctx.session_factory) as s:
            set_state(s, "bulk_345_loaded", {"names": sorted(loaded)})

    return {"newly_loaded": newly_loaded}
