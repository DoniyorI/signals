"""The worker process: runs scheduled jobs and requested jobs. The only process that calls
SEC, Alpaca or OpenFIGI, so every request shares one rate limiter."""

from collections.abc import Callable
from datetime import datetime

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from signals.config import Settings, get_settings
from signals.db.session import make_engine, make_session_factory, session_scope
from signals.domain.appstate import set_state
from signals.domain.calendars import ET
from signals.jobs import (
    JobContext,
    JobSpec,
    claim_next_request,
    load_all_jobs,
    make_ctx_builder,
    run_request,
)
from signals.logging import configure_logging, get_logger
from signals.sec.archive import RawArchive
from signals.sec.client import build_sec_client

log = get_logger(__name__)

CtxFactory = Callable[[JobSpec], JobContext]


def _run_scheduled(spec: JobSpec, ctx_factory: CtxFactory | None) -> Callable[[], None]:
    def run() -> None:
        if ctx_factory is None:
            return
        try:
            result = spec.func(ctx_factory(spec))
            log.info("scheduled_job_done", kind=spec.kind, result=result)
        except Exception as exc:  # logged; the job's own track_run row records details
            log.error("scheduled_job_failed", kind=spec.kind, error=f"{type(exc).__name__}: {exc}")

    return run


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
    session_factory: Callable[[], Session] = make_session_factory(
        make_engine(settings.database_url)
    )
    archive = RawArchive(settings.raw_archive_dir)

    def on_block(until: datetime) -> None:
        with session_scope(session_factory) as s:
            set_state(s, "sec_blocked_until", {"until": until.isoformat()})

    sec = build_sec_client(settings, archive=archive, on_block=on_block)
    specs = load_all_jobs()
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
