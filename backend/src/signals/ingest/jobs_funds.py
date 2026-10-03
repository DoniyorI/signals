"""Fund and stake jobs. Owned by workstream B.

`backfill_funds` and `bulk_check_funds` both walk the SEC's Form 13F Data Sets listing page
and load whatever they're missing (by job progress for the resumable backfill, by
`app_state["bulk_13f_loaded"]` for the weekly check), reusing `bulk_13f.load_13f_zip` for the
actual write. `_apply_acceptance` and `_gap_fill` are thin wrappers around workstream A's
`signals.ingest.bulk_345.apply_acceptance_times` and `signals.ingest.gap_fill.gap_fill`: they
import lazily so this module can be exercised (and its own tests can monkeypatch these two
names) before workstream A's modules exist.
"""

from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

import httpx

from signals.db.session import session_scope
from signals.domain.appstate import get_state, set_state
from signals.domain.calendars import ET
from signals.domain.types import FUND_FORMS, STAKE_FORMS
from signals.ingest.bulk_13f import list_13f_datasets, load_13f_zip
from signals.ingest.fund_changes import (
    compute_fund_changes,
    flag_value_unit_anomalies,
    refresh_fund_manager_stats,
)
from signals.jobs import JobContext, register_job, yield_for_priority
from signals.logging import get_logger
from signals.reference.cusip import OpenFigiClient, map_securities
from signals.reference.tracked_funds import load_curated, refresh_tracked_funds
from signals.sec.ratelimit import Priority

log = get_logger(__name__)

LISTING_URL = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
BULK_STATE_KEY = "bulk_13f_loaded"


def _apply_acceptance(ctx: JobContext) -> int:
    # Workstream A's module; not present in every worktree (see the module docstring).
    from signals.ingest import bulk_345  # pyright: ignore[reportAttributeAccessIssue]

    with session_scope(ctx.session_factory) as s:
        return bulk_345.apply_acceptance_times(s)


def _gap_fill(ctx: JobContext, form_types: frozenset[str], *, start: date, key: str) -> Any:
    from signals.ingest.gap_fill import gap_fill  # pyright: ignore[reportMissingImports]

    sub = dict(ctx.progress.get(key, {}))

    def save(p: dict) -> None:
        ctx.progress[key] = dict(p)
        ctx.save_progress(ctx.progress)
        yield_for_priority(ctx)

    result = gap_fill(
        ctx.sec,
        ctx.session_factory,
        form_types=form_types,
        start=start,
        end=ctx.now().astimezone(ET).date() - timedelta(days=1),
        settings=ctx.settings,
        archive=ctx.archive,
        progress=sub,
        save_progress=save,
    )
    if result.errors:
        raise RuntimeError(f"{key} has {result.errors} unresolved errors")
    return result


def _openfigi_client(ctx: JobContext) -> OpenFigiClient:
    key = (
        ctx.settings.openfigi_api_key.get_secret_value() if ctx.settings.openfigi_api_key else None
    )
    return OpenFigiClient(httpx.Client(), key)


def _fetch_datasets(ctx: JobContext) -> list:
    html = ctx.sec.get(
        LISTING_URL, priority=Priority.BULK, archive_as=("bulk", "listing_13f", "html")
    )
    return list_13f_datasets(html.decode("utf-8"))


@register_job("backfill_funds")
def backfill_funds(ctx: JobContext) -> dict:
    """Every Form 13F Data Set since `settings.backfill_start`, then acceptance times, then
    a gap fill for anything the bulk sets don't cover yet, then the derived tables.
    Resumable: already-loaded dataset names live in `ctx.progress["datasets_done"]`."""
    datasets_done: list[str] = list(ctx.progress.get("datasets_done", []))
    datasets = _fetch_datasets(ctx)
    for dataset in datasets:
        if dataset.end < ctx.settings.backfill_start or dataset.name in datasets_done:
            continue
        zip_bytes = ctx.sec.get(
            dataset.url, priority=Priority.BULK, archive_as=("bulk", dataset.name, "zip")
        )
        with session_scope(ctx.session_factory) as s:
            result = load_13f_zip(s, zip_bytes)
        log.info(
            "backfill_funds_dataset_loaded", dataset=dataset.name, accessions=result.accessions
        )
        datasets_done.append(dataset.name)
        ctx.progress["datasets_done"] = datasets_done
        ctx.save_progress(ctx.progress)
        yield_for_priority(ctx)

    _apply_acceptance(ctx)
    last_end = datasets[-1].end if datasets else ctx.settings.backfill_start
    _gap_fill(ctx, FUND_FORMS, start=last_end + timedelta(days=1), key="gap_fill_funds")
    _gap_fill(ctx, STAKE_FORMS, start=ctx.settings.stakes_start, key="gap_fill_stakes")

    with session_scope(ctx.session_factory) as s:
        compute_fund_changes(s)
    with session_scope(ctx.session_factory) as s:
        map_securities(s, _openfigi_client(ctx))
    with session_scope(ctx.session_factory) as s:
        flag_value_unit_anomalies(s)
    with session_scope(ctx.session_factory) as s:
        refresh_tracked_funds(
            s,
            curated=load_curated(),
            top_n=ctx.settings.tracked_funds_top_n,
            max_positions=ctx.settings.tracked_funds_max_positions,
        )
    return {"datasets_done": len(datasets_done)}


@register_job("bulk_check_funds", cron={"day_of_week": "mon", "hour": 3, "minute": 15})
def bulk_check_funds(ctx: JobContext) -> dict:
    """Weekly: load whatever Form 13F Data Set the listing has that isn't recorded in
    `app_state["bulk_13f_loaded"]` yet (a new quarterly set, or a corrected rolling one)."""
    with session_scope(ctx.session_factory) as s:
        state = get_state(s, BULK_STATE_KEY) or {}
    loaded: list[str] = list(state.get("loaded", []))
    datasets = _fetch_datasets(ctx)
    newly_loaded: list[str] = []
    for dataset in datasets:
        if dataset.name in loaded:
            continue
        zip_bytes = ctx.sec.get(
            dataset.url, priority=Priority.BULK, archive_as=("bulk", dataset.name, "zip")
        )
        with session_scope(ctx.session_factory) as s:
            load_13f_zip(s, zip_bytes)
        loaded.append(dataset.name)
        newly_loaded.append(dataset.name)
        with session_scope(ctx.session_factory) as s:
            set_state(s, BULK_STATE_KEY, {"loaded": loaded})
    return {"loaded": newly_loaded}


@register_job("cusip_map")
def cusip_map(ctx: JobContext) -> dict:
    """On request: resolve any `fund_positions.cusip` that still needs a `securities` row."""
    with session_scope(ctx.session_factory) as s:
        result = map_securities(s, _openfigi_client(ctx))
    return asdict(result)


@register_job("fund_changes")
def fund_changes(ctx: JobContext) -> dict:
    """On request (optionally scoped to `params["filer_ciks"]`): rebuild quarter-over-quarter
    changes and refresh each manager's latest-period summary stats."""
    filer_ciks = ctx.params.get("filer_ciks")
    with session_scope(ctx.session_factory) as s:
        n_changes = compute_fund_changes(s, filer_ciks=filer_ciks)
        n_managers = refresh_fund_manager_stats(s, filer_ciks=filer_ciks)
    return {"changes": n_changes, "managers": n_managers}


@register_job("tracked_funds_refresh", cron={"day_of_week": "sun", "hour": 5, "minute": 0})
def tracked_funds_refresh(ctx: JobContext) -> dict:
    """Weekly: recompute which fund managers the dashboard tracks."""
    with session_scope(ctx.session_factory) as s:
        n = refresh_tracked_funds(
            s,
            curated=load_curated(),
            top_n=ctx.settings.tracked_funds_top_n,
            max_positions=ctx.settings.tracked_funds_max_positions,
        )
    return {"tracked": n}
