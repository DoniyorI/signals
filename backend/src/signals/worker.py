"""The worker process: runs scheduled jobs and requested jobs. The only process that calls
SEC, Alpaca or OpenFIGI, so every request shares one rate limiter."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from signals.config import Settings, get_settings
from signals.db.models import IngestRun
from signals.db.session import make_engine, make_session_factory, session_scope
from signals.domain.appstate import get_state, set_state
from signals.domain.calendars import ET, now_et
from signals.jobs import (
    JobContext,
    JobSpec,
    claim_next_request,
    load_all_jobs,
    make_ctx_builder,
    recover_interrupted_requests,
    run_request,
    track_run,
)
from signals.logging import configure_logging, get_logger
from signals.sec.archive import RawArchive
from signals.sec.client import build_sec_client

log = get_logger(__name__)

CtxFactory = Callable[[JobSpec], JobContext]
WORKER_LOCK_KEY = 0x5349474E414C53


@contextmanager
def worker_lock(engine: Engine) -> Iterator[None]:
    """Hold a session advisory lock on a dedicated connection for the worker lifetime."""
    with engine.connect() as connection:
        acquired = connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": WORKER_LOCK_KEY}
        )
        if not acquired:
            raise RuntimeError("Another Signals worker is already running")
        try:
            yield
        finally:
            # Engine connections return to a pool; explicitly unlock before returning it.
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": WORKER_LOCK_KEY})


def recover_unfinished_runs(session: Session) -> int:
    """Mark interrupted legacy run records only while startup owns the singleton lock."""
    rows = session.scalars(
        select(IngestRun).where(IngestRun.finished_at.is_(None)).with_for_update()
    ).all()
    for run in rows:
        run.finished_at = now_et()
        run.errors += 1
        run.notes = {**(run.notes or {}), "exception": "Worker interrupted before completion"}
    session.flush()
    return len(rows)


def _run_scheduled(spec: JobSpec, ctx_factory: CtxFactory | None) -> Callable[[], None]:
    def run() -> None:
        if ctx_factory is None:
            return
        try:
            ctx = ctx_factory(spec)
            with track_run(ctx.session_factory, spec.kind) as run:
                result = spec.func(ctx) or {}
                run.notes.update(result)
                run.fetched = max(
                    run.fetched,
                    _result_count(result, ("fetched", "entries", "listed", "requested")),
                )
                run.new_rows = max(
                    run.new_rows, _result_count(result, ("new_rows", "new", "ingested", "rows"))
                )
                run.missed = max(run.missed, _result_count(result, ("missed", "missing")))
                run.errors = max(run.errors, _result_count(result, ("errors",)))
                if run.errors:
                    details = _error_details(result)
                    run.notes["error"] = (
                        "; ".join(details)
                        if details
                        else f"{run.errors} errors reported by {spec.kind}"
                    )
            log.info("scheduled_job_done", kind=spec.kind, result=result)
        except Exception as exc:  # the wrapper's durable row records escaping failures
            log.error("scheduled_job_failed", kind=spec.kind, error=f"{type(exc).__name__}: {exc}")

    return run


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


def build_scheduler(
    settings: Settings,
    *,
    specs: dict[str, JobSpec],
    ctx_factory: CtxFactory | None,
    poll_requests: Callable[[], None] | None = None,
) -> BlockingScheduler:
    scheduler = BlockingScheduler(executors={"default": ThreadPoolExecutor(4)}, timezone=ET)
    defaults = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 300}
    for kind, spec in specs.items():
        if spec.cron:
            trigger = CronTrigger(**spec.cron, timezone=ET)
        elif spec.interval_seconds:
            trigger = IntervalTrigger(seconds=spec.interval_seconds, timezone=ET)
        else:
            continue  # on-request only
        scheduler.add_job(_run_scheduled(spec, ctx_factory), trigger, id=kind, **defaults)
    # Two instances: a long backfill must not block short requested jobs.
    scheduler.add_job(
        poll_requests or (lambda: None),
        IntervalTrigger(seconds=5, timezone=ET),
        id="poll_job_requests",
        max_instances=2,
        coalesce=True,
        misfire_grace_time=30,
    )
    return scheduler


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_json)
    engine = make_engine(settings.database_url)
    with worker_lock(engine):
        _serve_worker(settings, make_session_factory(engine))


def _serve_worker(settings: Settings, session_factory: Callable[[], Session]) -> None:
    archive = RawArchive(settings.raw_archive_dir)

    def on_block(until: datetime) -> None:
        with session_scope(session_factory) as s:
            set_state(s, "sec_blocked_until", {"until": until.isoformat()})

    sec = build_sec_client(settings, archive=archive, on_block=on_block)
    with session_scope(session_factory) as s:
        pause = get_state(s, "sec_blocked_until")
    if pause and pause.get("until"):
        until = datetime.fromisoformat(pause["until"])
        if until > now_et():
            sec.blocked_until = until
    specs = load_all_jobs()
    # The lifetime advisory lock prevents recovery from stealing another live worker's run.
    with session_scope(session_factory) as s:
        recovered = recover_interrupted_requests(s)
        interrupted_runs = recover_unfinished_runs(s)
    if recovered:
        log.info("interrupted_backfills_recovered", count=recovered)
    if interrupted_runs:
        log.info("interrupted_ingest_runs_recorded", count=interrupted_runs)
    builder = make_ctx_builder(settings, session_factory, sec, archive)

    def ctx_for(spec: JobSpec) -> JobContext:
        return JobContext(
            settings=settings,
            session_factory=session_factory,
            sec=sec,
            archive=archive,
            request_id=None,
            params={},
            progress={},
            save_progress=lambda p: None,
        )

    def poll() -> None:
        with session_scope(session_factory) as s:
            req = claim_next_request(s)
            rid = req.id if req else None
        if rid is not None:
            run_request(builder, session_factory, rid)

    scheduler = build_scheduler(settings, specs=specs, ctx_factory=ctx_for, poll_requests=poll)
    log.info("worker_started", jobs=sorted(specs))
    scheduler.start()


if __name__ == "__main__":
    main()
