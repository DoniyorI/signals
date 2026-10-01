"""Durable cron catch-up using the same execution records as health."""

import time
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from signals import jobs as registry
from signals.db.models import IngestRun, JobRequest
from signals.db.session import session_scope
from signals.domain.appstate import get_state, set_state
from signals.domain.calendars import ET, is_sec_business_day
from signals.jobs import JobAlreadyRunning, JobContext, execute_job, register_job, track_run
from signals.sec.client import SecBlockedError

ORDER = (
    "reconcile_daily",
    "tickers_refresh",
    "bulk_check_insiders",
    "bulk_check_funds",
    "reference_refresh",
    "tracked_funds_refresh",
    "prices_daily",
    "analytics_full",
)


def last_due(cron: dict, now: datetime) -> datetime | None:
    """Find the latest CronTrigger fire instant, comparing UTC across DST folds."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    trigger = CronTrigger(**cron, timezone=ET)
    instant = now.astimezone(UTC)
    floor = datetime(1970, 1, 1, tzinfo=UTC)
    window = timedelta(days=1)
    while True:
        start = max(floor, instant - window)
        fire = trigger.get_next_fire_time(None, start.astimezone(ET))
        latest = None
        while fire is not None and fire.timestamp() <= instant.timestamp():
            latest = fire
            fire = trigger.get_next_fire_time(fire, fire)
        if latest is not None or start == floor:
            return latest
        window *= 2


def find_missed(session: Session, now: datetime) -> list[str]:
    specs = registry.load_all_jobs()
    kinds = {kind for kind, spec in specs.items() if spec.cron}
    successes: dict[str, datetime] = {}
    failures: dict[str, datetime] = {}
    active: set[str] = set()
    for row in session.scalars(select(IngestRun).where(IngestRun.job.in_(kinds))):
        if row.finished_at is None:
            active.add(row.job)
        else:
            target = failures if row.errors else successes
            target[row.job] = max(target.get(row.job, row.finished_at), row.finished_at)
    for req in session.scalars(select(JobRequest).where(JobRequest.kind.in_(kinds))):
        if req.status in ("requested", "queued", "running"):
            active.add(req.kind)
        elif req.finished_at is not None and req.status in ("done", "failed"):
            target = successes if req.status == "done" else failures
            target[req.kind] = max(target.get(req.kind, req.finished_at), req.finished_at)
    missed = []
    for kind in sorted(kinds - active):
        due = last_due(specs[kind].cron or {}, now)
        success, failed = successes.get(kind), failures.get(kind)
        incomplete_gap = False
        if kind == "reconcile_daily" and due is not None:
            checkpoint = get_state(session, "reconcile_last_day")
            target_day = due.astimezone(ET).date() - timedelta(days=1)
            while not is_sec_business_day(target_day):
                target_day -= timedelta(days=1)
            incomplete_gap = bool(checkpoint and date.fromisoformat(checkpoint["day"]) < target_day)
        if due is not None and (
            success is None
            or success < due
            or (failed is not None and failed > success)
            or incomplete_gap
        ):
            missed.append(kind)
    return missed


def _wait_for_sec(ctx: JobContext) -> None:
    # Persisted pause and shared client pause both apply, including a concurrent 403.
    while True:
        with session_scope(ctx.session_factory) as session:
            stored = get_state(session, "sec_blocked_until")
        until = datetime.fromisoformat(stored["until"]) if stored and stored.get("until") else None
        client_until = ctx.sec.blocked_until
        if client_until is not None and (until is None or client_until > until):
            until = client_until
        remaining = (until - ctx.now()).total_seconds() if until else 0
        if remaining <= 0:
            return
        ctx.sec.blocked_until = until
        time.sleep(min(30, remaining))


@register_job("catch_up", interval_seconds=900)
def catch_up(ctx: JobContext) -> dict:
    with track_run(ctx.session_factory, "catch_up") as tracker:
        with session_scope(ctx.session_factory) as session:
            missed = find_missed(session, ctx.now())
            backfill_active = (
                session.scalar(
                    select(JobRequest.id)
                    .where(
                        JobRequest.kind.in_(
                            (
                                "backfill_all",
                                "backfill_reference",
                                "backfill_insiders",
                                "backfill_funds",
                                "backfill_prices",
                            )
                        ),
                        JobRequest.status.in_(("requested", "running")),
                    )
                    .limit(1)
                )
                is not None
            )
            cron_kinds = [k for k, spec in registry.load_all_jobs().items() if spec.cron]
            maintenance_active = (
                session.scalar(
                    select(JobRequest.id)
                    .where(
                        JobRequest.kind.in_(cron_kinds),
                        JobRequest.status.in_(("requested", "queued", "running")),
                    )
                    .limit(1)
                )
                is not None
                or session.scalar(
                    select(IngestRun.id)
                    .where(IngestRun.job.in_(cron_kinds), IngestRun.finished_at.is_(None))
                    .limit(1)
                )
                is not None
            )
        state = {
            "status": "running",
            "started_at": ctx.now().isoformat(),
            "finished_at": None,
            "ran": [],
            "behind": missed,
            "error": None,
        }

        def save():
            with session_scope(ctx.session_factory) as session:
                set_state(session, "catch_up", state)

        save()
        try:
            if backfill_active:
                state["deferred"] = "Historical backfill is active"
            elif maintenance_active:
                state["deferred"] = "Scheduled maintenance is already running or queued"
            else:
                specs = registry.load_all_jobs()
                ordered = [k for k in ORDER if k in missed]
                ordered += sorted(set(missed) - set(ORDER))
                if ordered and "analytics_full" in specs and "analytics_full" not in ordered:
                    ordered.append("analytics_full")
                # Keep analytics last, including future additional cron kinds.
                ordered = [k for k in ordered if k != "analytics_full"] + (
                    ["analytics_full"] if "analytics_full" in ordered else []
                )
                for kind in ordered:
                    _wait_for_sec(ctx)
                    with session_scope(ctx.session_factory) as session:
                        if kind != "analytics_full" and kind not in find_missed(session, ctx.now()):
                            continue
                    child = replace(
                        ctx,
                        request_id=None,
                        params={**ctx.params, "catch_up": True},
                        progress={},
                        save_progress=lambda p: None,
                    )
                    try:
                        execute_job(specs[kind], child)
                    except JobAlreadyRunning:
                        # Defer downstream dependencies until the next check.
                        state["deferred"] = f"{kind} is already running or queued"
                        break
                    except SecBlockedError:
                        _wait_for_sec(ctx)
                        execute_job(specs[kind], child)
                    state["ran"].append(kind)
                    save()
            state["status"] = "done"
        except Exception as exc:
            state["status"] = "error"
            state["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            with session_scope(ctx.session_factory) as session:
                state["behind"] = find_missed(session, ctx.now())
            state["finished_at"] = ctx.now().isoformat()
            save()
            tracker.notes.update(state)
        return state
