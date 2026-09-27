"""Job registry, job requests (a small DB-backed queue) and run tracking.

Workstreams register jobs with @register_job in their own modules; load_all_jobs() imports
them. Anything outside the worker (CLI, API) only *requests* jobs; the worker runs them, so
all outside traffic shares the worker's single SEC rate limiter.
"""

import importlib
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
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
)

BACKFILL_STEPS = (
    "backfill_reference",
    "backfill_insiders",
    "backfill_funds",
    "backfill_prices",
    "analytics_full",
)


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


def register_job(kind: str, *, cron: dict | None = None, interval_seconds: int | None = None):
    def decorator(func: Callable[[JobContext], dict | None]):
        JOBS[kind] = JobSpec(kind, func, cron=cron, interval_seconds=interval_seconds)
        return func

    return decorator


def load_all_jobs() -> dict[str, JobSpec]:
    for module in JOB_MODULES:
        importlib.import_module(module)
    return JOBS


# ----------------------------------------------------------------------------- requests
def request_job(
    session: Session, kind: str, params: dict | None = None, *, coalesce: bool = True
) -> int:
    """Queue a job. A pending request of the same kind absorbs this one (list params union)."""
    params = dict(params or {})
    if coalesce:
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


def claim_next_request(session: Session) -> JobRequest | None:
    req = session.execute(
        select(JobRequest)
        .where(JobRequest.status == "requested")
        .order_by(JobRequest.requested_at, JobRequest.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if req is not None:
        req.status = "running"
        req.started_at = now_et()
        session.flush()
    return req


def _save_progress(session_factory: Callable[[], Session], request_id: int, progress: dict):
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
        result = spec.func(ctx) or {}
        ctx.progress["result"] = result
    except Exception as exc:  # recorded on the request row, surfaced by /api/health
        status, error = "failed", f"{type(exc).__name__}: {exc}"
        log.error("job_failed", kind=kind, request_id=request_id, error=error)
    with session_scope(session_factory) as s:
        req = s.get(JobRequest, request_id)
        if req is not None:
            req.status = status
            req.error = error
            req.progress = dict(ctx.progress)
            req.finished_at = now_et()


# ----------------------------------------------------------------------------- run log
@dataclass
class RunTracker:
    fetched: int = 0
    new_rows: int = 0
    missed: int = 0
    errors: int = 0
    notes: dict[str, Any] = field(default_factory=dict)


@contextmanager
def track_run(session_factory: Callable[[], Session], job: str) -> Generator[RunTracker]:
    """Always writes an ingest_runs row, even when the body raises (then re-raises)."""
    started = now_et()
    tracker = RunTracker()
    try:
        yield tracker
    except BaseException as exc:
        tracker.errors += 1
        tracker.notes["exception"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        with session_scope(session_factory) as s:
            s.add(
                IngestRun(
                    job=job,
                    started_at=started,
                    finished_at=now_et(),
                    fetched=tracker.fetched,
                    new_rows=tracker.new_rows,
                    missed=tracker.missed,
                    errors=tracker.errors,
                    notes=tracker.notes,
                )
            )


# ----------------------------------------------------------------------------- built-in jobs
@register_job("backfill_all")
def backfill_all(ctx: JobContext) -> dict:
    """Run every backfill step in order; resumable (finished steps are skipped)."""
    done: list[str] = list(ctx.progress.get("done_steps", []))
    steps: dict[str, dict] = dict(ctx.progress.get("steps", {}))
    for kind in BACKFILL_STEPS:
        if kind in done:
            continue
        spec = JOBS.get(kind)
        if spec is None:
            raise KeyError(f"backfill step {kind!r} is not registered")
        sub = dict(steps.get(kind, {}))

        def save_sub(p: dict, kind: str = kind) -> None:
            steps[kind] = dict(p)
            ctx.progress["steps"] = steps
            ctx.save_progress(ctx.progress)

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
        result = spec.func(step_ctx) or {}
        sub["result"] = result
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
    for acc in accessions:
        with session_scope(ctx.session_factory) as s:
            outcome = reparse_accession(s, acc, settings=ctx.settings, archive=ctx.archive)
        counts["parsed" if outcome.status == "parsed" else "error"] += 1
    return counts
