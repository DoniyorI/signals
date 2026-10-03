"""Job registry, job requests (a small DB-backed queue) and run tracking.

Workstreams register jobs with @register_job in their own modules; load_all_jobs() imports
them. Anything outside the worker (CLI, API) only *requests* jobs; the worker runs them, so
all outside traffic shares the worker's single SEC rate limiter.
"""

import importlib
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import case, select, text
from sqlalchemy.orm import Session

from signals.config import Settings
from signals.db.models import Filing, IngestRun, JobRequest
from signals.db.session import session_scope
from signals.domain.calendars import now_et
from signals.logging import get_logger
from signals.sec.archive import RawArchive
from signals.sec.client import SecClient

log = get_logger(__name__)

JOB_MODULES = (
    "signals.ingest.jobs_insider",
    "signals.ingest.jobs_funds",
    "signals.reference.jobs",
    "signals.prices.jobs",
    "signals.analytics.jobs",
    "signals.catchup",
    "signals.completeness",
)

BACKFILL_STEPS = (
    "backfill_reference",
    "backfill_insiders",
    "backfill_funds",
    "backfill_prices",
    "analytics_full",
    "completeness_check",
)
RESUMABLE_JOBS = frozenset((*BACKFILL_STEPS, "backfill_all", "gap_fill"))
PRIORITY_JOBS = frozenset(("refresh_insider_performance",))


@dataclass
class JobContext:
    settings: Settings
    session_factory: Callable[[], Session]
    sec: SecClient
    archive: RawArchive
    request_id: int | None
    params: dict[str, Any]
    progress: dict[str, Any]
    save_progress: Callable[[dict[str, Any]], None]
    now: Callable[[], datetime] = now_et


@dataclass(frozen=True)
class JobSpec:
    kind: str
    func: Callable[[JobContext], dict | None]
    cron: dict | None = None
    interval_seconds: int | None = None


JOBS: dict[str, JobSpec] = {}


def register_job[F: Callable[[JobContext], dict | None]](
    kind: str, *, cron: dict | None = None, interval_seconds: int | None = None
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        JOBS[kind] = JobSpec(kind, func, cron=cron, interval_seconds=interval_seconds)
        return func

    return decorator


def load_all_jobs() -> dict[str, JobSpec]:
    from signals.ingest.handlers import register_all_handlers

    register_all_handlers()
    for module in JOB_MODULES:
        importlib.import_module(module)
    return JOBS


# ----------------------------------------------------------------------------- requests
def request_job(
    session: Session, kind: str, params: dict | None = None, *, coalesce: bool = True
) -> int:
    """Queue/coalesce a job; identical backfill retries retain their existing checkpoint."""
    params = dict(params or {})
    if kind == "refresh_insider_performance":
        owner = params.get("owner_cik")
        if type(owner) is not int or owner <= 0:
            raise ValueError("refresh_insider_performance requires a positive integer owner_cik")
        # Browser mounts can race before either INSERT is visible. Serialize only this
        # owner until commit; refreshes for other owners keep distinct queue entries.
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"{kind}:{owner}"},
        )
        existing = session.scalars(
            select(JobRequest)
            .where(
                JobRequest.kind == kind,
                JobRequest.params.contains({"owner_cik": owner}),
                JobRequest.status.in_(("requested", "queued", "running")),
            )
            .order_by(JobRequest.id)
            .limit(1)
            .with_for_update()
        ).one_or_none()
        if existing is not None:
            return existing.id
    elif kind in RESUMABLE_JOBS:
        existing = session.scalars(
            select(JobRequest)
            .where(
                JobRequest.kind == kind,
                JobRequest.params == params,
                JobRequest.status.in_(("requested", "running")),
            )
            .order_by(JobRequest.id)
            .limit(1)
            .with_for_update()
        ).one_or_none()
        if existing is not None:
            return existing.id
        if coalesce:
            failed = session.scalars(
                select(JobRequest)
                .where(
                    JobRequest.kind == kind,
                    JobRequest.params == params,
                    JobRequest.status == "failed",
                )
                .order_by(JobRequest.id.desc())
                .limit(1)
                .with_for_update()
            ).one_or_none()
            if failed is not None:
                _requeue(failed)
                session.flush()
                return failed.id
    elif coalesce:
        existing = session.execute(
            select(JobRequest)
            .where(JobRequest.kind == kind, JobRequest.status == "requested")
            .order_by(JobRequest.id)
            .limit(1)
            .with_for_update()
        ).scalar_one_or_none()
        if existing is not None:
            merged = dict(existing.params)
            for key, value in params.items():
                if isinstance(value, list) and isinstance(merged.get(key), list):
                    merged[key] = sorted(set(merged[key]) | set(value))
                else:
                    merged.setdefault(key, value)
            existing.params = merged
            session.flush()
            return existing.id
    req = JobRequest(kind=kind, params=params)
    session.add(req)
    session.flush()
    return req.id


def _requeue(req: JobRequest) -> None:
    req.status = "requested"
    req.requested_at = now_et()
    req.started_at = req.finished_at = req.error = None


def recover_interrupted_requests(session: Session) -> int:
    """Requeue interrupted idempotent jobs at exclusive worker startup, retaining progress.

    Call only after acquiring the worker's exclusive advisory lock. Without that lock,
    status alone cannot distinguish an interrupted request from another worker's live run.
    Failed jobs are deliberately untouched; only resumable backfill retries reuse them.
    """
    rows = session.scalars(
        select(JobRequest)
        .where(JobRequest.status == "running")
        .order_by(JobRequest.id)
        .with_for_update()
    ).all()
    for req in rows:
        _requeue(req)
    session.flush()
    return len(rows)


def claim_next_request(session: Session) -> JobRequest | None:
    req = session.execute(
        select(JobRequest)
        .where(JobRequest.status == "requested")
        .order_by(
            case((JobRequest.kind.in_(PRIORITY_JOBS), 0), else_=1),
            JobRequest.requested_at,
            JobRequest.id,
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if req is not None:
        req.status = "running"
        req.started_at = now_et()
        session.flush()
    return req


def _save_progress(session_factory: Callable[[], Session], request_id: int, progress: dict):
    progress["updated_at"] = now_et().isoformat()
    with session_scope(session_factory) as s:
        req = s.get(JobRequest, request_id)
        if req is not None:
            req.progress = dict(progress)


def make_ctx_builder(
    settings: Settings,
    session_factory: Callable[[], Session],
    sec: SecClient,
    archive: RawArchive,
) -> Callable[[JobRequest], JobContext]:
    def build(req: JobRequest) -> JobContext:
        rid = req.id
        return JobContext(
            settings=settings,
            session_factory=session_factory,
            sec=sec,
            archive=archive,
            request_id=rid,
            params=dict(req.params),
            progress=dict(req.progress),
            save_progress=lambda p: _save_progress(session_factory, rid, p),
        )

    return build


def run_request(
    ctx_builder: Callable[[JobRequest], JobContext],
    session_factory: Callable[[], Session],
    request_id: int,
) -> None:
    with session_scope(session_factory) as s:
        req = s.get(JobRequest, request_id)
        if req is None:
            raise LookupError(f"job request {request_id} not found")
        kind = req.kind
        ctx = ctx_builder(req)
    status, error = "done", None
    try:
        spec = JOBS.get(kind)
        if spec is None:
            raise KeyError(f"unknown job kind {kind!r}")
        result = execute_job(spec, ctx)
        ctx.progress["result"] = result
        count, details = reported_errors(result)
        if count:
            raise RuntimeError(
                "; ".join(details) if details else f"{count} errors reported by {kind}"
            )
    except JobAlreadyRunning:
        status = "requested"
    except Exception as exc:  # recorded on the request row, surfaced by /api/health
        status, error = "failed", f"{type(exc).__name__}: {exc}"
        log.error("job_failed", kind=kind, request_id=request_id, error=error)
    with session_scope(session_factory) as s:
        req = s.get(JobRequest, request_id)
        if req is not None:
            req.status = status
            req.error = error
            req.progress = dict(ctx.progress)
            req.finished_at = now_et() if status != "requested" else None
            if status == "requested":
                req.started_at = None
                req.requested_at = now_et()


def reported_errors(result: dict) -> tuple[int, list[str]]:
    """Read explicit error counters, including per-day results; aliases count once."""
    count = max((result[k] for k in ("errors", "error") if type(result.get(k)) is int), default=0)
    details = [str(message) for message in result.get("error_details", [])]
    for row in result.get("results", []):
        if isinstance(row, dict):
            child_count, child_details = reported_errors(row)
            count += child_count
            details.extend(child_details)
    return count, details


# ----------------------------------------------------------------------------- run log
@dataclass
class RunTracker:
    fetched: int = 0
    new_rows: int = 0
    missed: int = 0
    errors: int = 0
    notes: dict[str, Any] = field(default_factory=dict)


_ACTIVE_RUN: ContextVar[tuple[str, RunTracker] | None] = ContextVar("active_run", default=None)


@contextmanager
def track_run(session_factory: Callable[[], Session], job: str) -> Generator[RunTracker]:
    """Always writes an ingest_runs row, even when the body raises (then re-raises)."""
    active = _ACTIVE_RUN.get()
    if active is not None and active[0] == job:
        yield active[1]
        return
    started = now_et()
    tracker = RunTracker()
    with session_scope(session_factory) as s:
        row = IngestRun(job=job, started_at=started, finished_at=None)
        s.add(row)
        s.flush()
        run_id = row.id
    token = _ACTIVE_RUN.set((job, tracker))
    try:
        yield tracker
    except JobDeferred as exc:
        tracker.notes["deferred"] = str(exc)
        raise
    except BaseException as exc:
        tracker.errors = max(1, tracker.errors)
        tracker.notes["exception"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        _ACTIVE_RUN.reset(token)
        with session_scope(session_factory) as s:
            row = s.get(IngestRun, run_id)
            assert row is not None
            row.finished_at = now_et()
            row.fetched, row.new_rows, row.missed = (
                tracker.fetched,
                tracker.new_rows,
                tracker.missed,
            )
            row.errors, row.notes = tracker.errors, dict(tracker.notes)


class JobAlreadyRunning(RuntimeError):
    """A scheduled, requested or catch-up execution already owns this job."""


class JobDeferred(JobAlreadyRunning):
    """A historical request yielded at a durable checkpoint for priority work."""


def yield_for_priority(ctx: JobContext) -> None:
    """After saving a historical checkpoint, release execution guards by unwinding.

    Scheduled work has no durable request to requeue. Check the parent request's kind
    so a priority refresh cannot defer itself through its own progress callbacks.
    """
    if ctx.request_id is None:
        return
    with session_scope(ctx.session_factory) as session:
        parent = session.get(JobRequest, ctx.request_id)
        if parent is None or parent.kind not in RESUMABLE_JOBS:
            return
        waiting = session.scalar(
            select(JobRequest.kind)
            .where(
                JobRequest.kind.in_(PRIORITY_JOBS),
                JobRequest.id != ctx.request_id,
                JobRequest.status.in_(("requested", "queued", "running")),
            )
            .limit(1)
        )
    if waiting:
        raise JobDeferred(f"Yielded to requested {waiting}")


_JOB_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_MAINTENANCE_LOCK = threading.RLock()


def _result_count(result: dict, keys: tuple[str, ...]) -> int:
    """Aggregate returned per-day results without counting alias counters twice."""
    own = next((result[key] for key in keys if isinstance(result.get(key), int)), 0)
    return own + sum(
        _result_count(row, keys) for row in result.get("results", []) if isinstance(row, dict)
    )


def _error_details(result: dict) -> list[str]:
    details = [str(message) for message in result.get("error_details", [])]
    for row in result.get("results", []):
        if isinstance(row, dict):
            details.extend(_error_details(row))
    return details


def execute_job(spec: JobSpec, ctx: JobContext) -> dict:
    # The lifetime worker DB lock ensures a single process; this lock closes races
    # between its scheduled, catch-up and request threads without locking ingest rows.
    with _LOCKS_GUARD:
        lock = _JOB_LOCKS.setdefault(spec.kind, threading.Lock())
    if not lock.acquire(blocking=False):
        raise JobAlreadyRunning(spec.kind)
    maintenance = bool(spec.cron) or spec.kind in (
        *BACKFILL_STEPS,
        "backfill_all",
        "catch_up",
        "gap_fill",
        *PRIORITY_JOBS,
    )
    if maintenance and not _MAINTENANCE_LOCK.acquire(blocking=False):
        lock.release()
        raise JobAlreadyRunning("Maintenance is already running")
    try:
        with session_scope(ctx.session_factory) as s:
            running = s.scalar(
                select(IngestRun.id)
                .where(IngestRun.job == spec.kind, IngestRun.finished_at.is_(None))
                .limit(1)
            )
            queued = select(JobRequest.id).where(
                JobRequest.kind == spec.kind,
                JobRequest.status.in_(("requested", "queued", "running")),
            )
            if ctx.request_id is not None:
                queued = queued.where(
                    JobRequest.id != ctx.request_id, JobRequest.status == "running"
                )
            if running is not None or s.scalar(queued.limit(1)) is not None:
                raise JobAlreadyRunning(spec.kind)
        with track_run(ctx.session_factory, spec.kind) as tracker:
            result = spec.func(ctx) or {}
            tracker.notes.update(result)
            ctx.progress["result"] = result
            tracker.fetched = max(
                tracker.fetched,
                _result_count(result, ("fetched", "entries", "listed", "requested")),
            )
            tracker.new_rows = max(
                tracker.new_rows, _result_count(result, ("new_rows", "new", "ingested", "rows"))
            )
            tracker.missed = max(tracker.missed, _result_count(result, ("missed", "missing")))
            count, details = reported_errors(result)
            tracker.errors = max(tracker.errors, count)
            if count:
                raise RuntimeError(
                    "; ".join(details) if details else f"{count} errors reported by {spec.kind}"
                )
            return result
    finally:
        if maintenance:
            _MAINTENANCE_LOCK.release()
        lock.release()


# ----------------------------------------------------------------------------- built-in jobs
@register_job("backfill_all")
def backfill_all(ctx: JobContext) -> dict:
    """Run every backfill step in order; resumable (finished steps are skipped)."""
    done: list[str] = list(ctx.progress.get("done_steps", []))
    steps: dict[str, dict] = dict(ctx.progress.get("steps", {}))
    for kind in BACKFILL_STEPS:
        if kind in done:
            continue
        yield_for_priority(ctx)
        spec = JOBS.get(kind)
        if spec is None:
            raise KeyError(f"backfill step {kind!r} is not registered")
        sub = dict(steps.get(kind, {}))

        def save_sub(p: dict, kind: str = kind) -> None:
            p["updated_at"] = ctx.now().isoformat()
            steps[kind] = dict(p)
            ctx.progress["steps"] = steps
            ctx.save_progress(ctx.progress)
            yield_for_priority(ctx)

        step_ctx = JobContext(
            settings=ctx.settings,
            session_factory=ctx.session_factory,
            sec=ctx.sec,
            archive=ctx.archive,
            request_id=ctx.request_id,
            params=ctx.params,
            progress=sub,
            save_progress=save_sub,
            now=ctx.now,
        )
        log.info("backfill_step_start", step=kind)
        result = execute_job(spec, step_ctx)
        sub["result"] = result
        sub["updated_at"] = ctx.now().isoformat()
        steps[kind] = sub
        done.append(kind)
        ctx.progress.update({"steps": steps, "done_steps": done})
        ctx.save_progress(ctx.progress)
    return {"done_steps": done}


@register_job("reparse")
def reparse(ctx: JobContext) -> dict:
    """Re-run parsers from the raw archive for given accessions or a parse status."""
    from signals.ingest.pipeline import reparse_accession

    accessions: list[str] = list(ctx.params.get("accessions", []))
    if not accessions and ctx.params.get("status"):
        with session_scope(ctx.session_factory) as s:
            accessions = list(
                s.scalars(
                    select(Filing.accession_no).where(Filing.parse_status == ctx.params["status"])
                )
            )
    counts = {"parsed": 0, "error": 0}
    details: list[str] = []
    for acc in accessions:
        with session_scope(ctx.session_factory) as s:
            outcome = reparse_accession(s, acc, settings=ctx.settings, archive=ctx.archive)
        counts["parsed" if outcome.status == "parsed" else "error"] += 1
        if outcome.status != "parsed":
            details.append(f"{acc}: {outcome.error or outcome.status}")
    if details:
        return {**counts, "error_details": details}
    return counts
