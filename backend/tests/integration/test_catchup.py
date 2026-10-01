from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from signals import jobs
from signals.db.models import IngestRun, JobRequest
from signals.domain.appstate import get_state, set_state
from signals.domain.calendars import ET, is_sec_business_day
from signals.jobs import JobContext, JobSpec
from signals.sec.client import SecClient
from tests.support import MockRouter

NOW = datetime(2026, 9, 30, 12, tzinfo=ET)
ORDER = [
    "reconcile_daily",
    "tickers_refresh",
    "bulk_check_insiders",
    "bulk_check_funds",
    "reference_refresh",
    "tracked_funds_refresh",
    "prices_daily",
    "analytics_full",
]


def isolated_specs(monkeypatch, kinds):
    jobs.load_all_jobs()
    specs = {k: JobSpec(k, lambda ctx: {}, cron={"hour": 2}) for k in kinds}
    monkeypatch.setattr(jobs, "JOBS", specs)
    monkeypatch.setattr(jobs, "load_all_jobs", lambda: specs)
    return specs


@pytest.mark.parametrize(
    "cron,instant,expected",
    [
        ({"hour": 5}, "2026-09-30T04:59:59-04:00", "2026-09-29T05:00:00-04:00"),
        ({"hour": 5}, "2026-09-30T05:00:00-04:00", "2026-09-30T05:00:00-04:00"),
        ({"hour": 5}, "2026-09-30T05:00:01-04:00", "2026-09-30T05:00:00-04:00"),
        (
            {"hour": 18, "minute": 30, "day_of_week": "mon-fri"},
            "2026-09-28T08:00:00-04:00",
            "2026-09-25T18:30:00-04:00",
        ),
        (
            {"hour": 3, "day_of_week": "mon"},
            "2026-09-27T12:00:00-04:00",
            "2026-09-21T03:00:00-04:00",
        ),
        ({"hour": 5}, "2026-03-08T04:59:00-04:00", "2026-03-07T05:00:00-05:00"),
        ({"hour": 5}, "2026-03-08T05:01:00-04:00", "2026-03-08T05:00:00-04:00"),
        ({"hour": 5}, "2026-11-01T04:59:00-05:00", "2026-10-31T05:00:00-04:00"),
        ({"hour": 5}, "2026-11-01T05:01:00-05:00", "2026-11-01T05:00:00-05:00"),
        ({"hour": 1, "minute": 30}, "2026-11-01T06:45:00+00:00", "2026-11-01T01:30:00-05:00"),
        ({"year": 2027, "hour": 5}, "2026-09-30T12:00:00-04:00", None),
    ],
)
def test_last_due(cron, instant, expected):
    from signals.catchup import last_due

    actual = last_due(cron, datetime.fromisoformat(instant))
    assert (actual.timestamp() if actual else None) == (
        datetime.fromisoformat(expected).timestamp() if expected else None
    )
    if actual:
        assert str(actual.tzinfo) == "America/New_York"


def test_find_missed_uses_success_failure_and_active_records(session, monkeypatch):
    from signals.catchup import find_missed

    kinds = [
        "old",
        "fresh",
        "failed",
        "running",
        "queued",
        "active_run",
        "never",
        "request_success",
    ]
    isolated_specs(monkeypatch, kinds)
    for kind, hours, errors in [("old", 48, 0), ("fresh", 1, 0), ("failed", 1, 1)]:
        session.add(
            IngestRun(
                job=kind,
                started_at=NOW - timedelta(hours=hours, minutes=1),
                finished_at=NOW - timedelta(hours=hours),
                errors=errors,
            )
        )
    session.add(
        IngestRun(
            job="failed",
            started_at=NOW - timedelta(hours=3),
            finished_at=NOW - timedelta(hours=2),
            errors=0,
        )
    )
    session.add(IngestRun(job="active_run", started_at=NOW, finished_at=None))
    for kind, status in [
        ("running", "running"),
        ("queued", "requested"),
        ("request_success", "done"),
    ]:
        session.add(
            JobRequest(
                kind=kind,
                status=status,
                requested_at=NOW - timedelta(hours=1),
                finished_at=NOW - timedelta(minutes=10) if status == "done" else None,
            )
        )
    session.flush()
    assert set(find_missed(session, NOW)) == {"old", "failed", "never"}


def test_catchup_dependency_order_and_idempotence(
    session, session_factory, settings, tmp_archive, monkeypatch
):
    from signals.catchup import catch_up

    calls = []
    specs = isolated_specs(monkeypatch, reversed(ORDER))
    for kind, spec in list(specs.items()):
        specs[kind] = JobSpec(kind, lambda ctx, k=kind: calls.append(k) or {}, cron=spec.cron)
    monkeypatch.setattr(jobs, "now_et", lambda: NOW)
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        None,
        {},
        {},
        lambda p: None,
        lambda: NOW,
    )
    first = catch_up(ctx)
    assert calls == ORDER and calls.count("analytics_full") == 1
    assert first["ran"] == ORDER
    assert catch_up(ctx)["ran"] == []
    rows = list(session.scalars(select(IngestRun)))
    assert len([r for r in rows if r.job == "catch_up"]) == 2
    state = get_state(session, "catch_up")
    assert state is not None and state["behind"] == []


def test_running_job_cannot_be_started_again(session, session_factory, settings, tmp_archive):
    from signals.jobs import JobAlreadyRunning, execute_job

    called = []
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        None,
        {},
        {},
        lambda p: None,
    )
    session.add(IngestRun(job="prices_daily", started_at=NOW, finished_at=None))
    session.flush()
    with pytest.raises(JobAlreadyRunning):
        execute_job(JobSpec("prices_daily", lambda ctx: called.append(True)), ctx)
    assert called == []


def test_track_run_visible_before_completion(session, session_factory):
    with jobs.track_run(session_factory, "visible"):
        row = session.scalar(select(IngestRun).where(IngestRun.job == "visible"))
        assert row is not None and row.finished_at is None
    session.expire(row)
    assert row.finished_at is not None


@pytest.mark.parametrize("gap", [9, 90])
def test_catchup_reconciles_every_outage_business_day(
    gap, session, session_factory, settings, tmp_archive, monkeypatch
):
    from signals.ingest import jobs_insider
    from signals.ingest.indexes import ReconcileResult

    yesterday = NOW.date() - timedelta(days=1)
    last = yesterday - timedelta(days=gap)
    set_state(session, "reconcile_last_day", {"day": last.isoformat()})
    calls = []

    def reconcile(client, factory, day, **kwargs):
        calls.append(day)
        return ReconcileResult(day, 0, 0, 0, 0)

    monkeypatch.setattr(jobs_insider, "reconcile_day", reconcile)
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        None,
        {"catch_up": True},
        {},
        lambda p: None,
        lambda: NOW,
    )
    jobs_insider.reconcile_daily(ctx)
    expected = [
        last + timedelta(days=n)
        for n in range(1, gap + 1)
        if is_sec_business_day(last + timedelta(days=n))
    ]
    assert calls == expected


def test_cron_misfires_and_catchup_startup_interval(settings):
    from signals.worker import build_scheduler

    specs = jobs.load_all_jobs()
    scheduler = build_scheduler(settings, specs=specs, ctx_factory=None)
    for kind, spec in specs.items():
        if spec.cron:
            scheduled = scheduler.get_job(kind)
            assert scheduled is not None
            assert scheduled.coalesce is True and scheduled.misfire_grace_time is None
    catchup = scheduler.get_job("catch_up")
    assert catchup is not None
    assert catchup.trigger.interval.total_seconds() == 900
    assert abs((catchup.next_run_time - datetime.now(ET)).total_seconds()) < 5


def test_catchup_refreshes_analytics_after_inputs_even_if_analytics_was_fresh(
    session, session_factory, settings, tmp_archive, monkeypatch
):
    from signals.catchup import catch_up

    calls = []
    specs = isolated_specs(monkeypatch, ["prices_daily", "analytics_full"])
    for kind, spec in list(specs.items()):
        specs[kind] = JobSpec(kind, lambda ctx, k=kind: calls.append(k) or {}, cron=spec.cron)
    session.add(
        IngestRun(
            job="analytics_full",
            started_at=NOW - timedelta(hours=1),
            finished_at=NOW - timedelta(minutes=30),
            errors=0,
        )
    )
    session.flush()
    monkeypatch.setattr(jobs, "now_et", lambda: NOW)
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        None,
        {},
        {},
        lambda p: None,
        lambda: NOW,
    )
    catch_up(ctx)
    assert calls == ["prices_daily", "analytics_full"]


def test_failed_reconcile_day_keeps_checkpoint_before_gap(
    session, session_factory, settings, tmp_archive, monkeypatch
):
    from signals.ingest import jobs_insider
    from signals.ingest.indexes import ReconcileResult

    last = NOW.date() - timedelta(days=9)
    set_state(session, "reconcile_last_day", {"day": last.isoformat()})
    monkeypatch.setattr(
        jobs_insider,
        "reconcile_day",
        lambda client, factory, day, **kwargs: ReconcileResult(day, 1, 1, 0, 1),
    )
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        None,
        {"catch_up": True},
        {},
        lambda p: None,
        lambda: NOW,
    )
    result = jobs_insider.reconcile_daily(ctx)
    assert len(result["results"]) == 1
    assert get_state(session, "reconcile_last_day") == {"day": last.isoformat()}


def test_catchup_waits_out_persisted_sec_pause(
    session, session_factory, settings, tmp_archive, monkeypatch
):
    from signals import catchup

    instant = [NOW]
    until = NOW + timedelta(seconds=65)
    set_state(session, "sec_blocked_until", {"until": until.isoformat()})
    calls = []
    specs = isolated_specs(monkeypatch, ["reconcile_daily"])
    specs["reconcile_daily"] = JobSpec(
        "reconcile_daily", lambda ctx: calls.append(ctx.now()) or {}, cron={"hour": 2}
    )

    def sleep(seconds):
        instant[0] += timedelta(seconds=seconds)

    monkeypatch.setattr(catchup.time, "sleep", sleep)
    monkeypatch.setattr(jobs, "now_et", lambda: instant[0])
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        None,
        {},
        {},
        lambda p: None,
        lambda: instant[0],
    )
    catchup.catch_up(ctx)
    assert calls == [until]
    assert ctx.sec.blocked_until == until


def test_catchup_defers_while_historical_backfill_is_queued(
    session, session_factory, settings, tmp_archive, monkeypatch
):
    from signals.catchup import catch_up

    isolated_specs(monkeypatch, ["reconcile_daily"])
    session.add(JobRequest(kind="backfill_all", status="requested", requested_at=NOW))
    session.flush()
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        None,
        {},
        {},
        lambda p: None,
        lambda: NOW,
    )
    result = catch_up(ctx)
    assert result["ran"] == [] and result["behind"] == ["reconcile_daily"]
    assert result["deferred"] == "Historical backfill is active"


def test_same_job_concurrent_execution_is_guarded(db_engine, settings, tmp_archive):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from sqlalchemy import delete

    from signals.db.session import make_session_factory, session_scope
    from signals.jobs import JobAlreadyRunning, execute_job

    entered, release = Event(), Event()
    factory = make_session_factory(db_engine)

    def work(ctx):
        entered.set()
        assert release.wait(5)
        return {}

    ctx = JobContext(
        settings,
        factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        None,
        {},
        {},
        lambda p: None,
    )
    spec = JobSpec("concurrency_probe", work, cron={"hour": 2})
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(execute_job, spec, ctx)
            try:
                assert entered.wait(5)
                with pytest.raises(JobAlreadyRunning):
                    execute_job(spec, ctx)
            finally:
                release.set()
            running.result(timeout=5)
    finally:
        with session_scope(factory) as session:
            session.execute(delete(IngestRun).where(IngestRun.job == "concurrency_probe"))


def test_catchup_does_not_run_analytics_ahead_of_queued_prices(
    session, session_factory, settings, tmp_archive, monkeypatch
):
    from signals.catchup import catch_up

    calls = []
    specs = isolated_specs(monkeypatch, ["prices_daily", "analytics_full"])
    for kind, spec in list(specs.items()):
        specs[kind] = JobSpec(kind, lambda ctx, k=kind: calls.append(k) or {}, cron=spec.cron)
    session.add(JobRequest(kind="prices_daily", status="requested", requested_at=NOW))
    session.flush()
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        None,
        {},
        {},
        lambda p: None,
        lambda: NOW,
    )
    result = catch_up(ctx)
    assert calls == [] and result["ran"] == []
    assert result["behind"] == ["analytics_full"]


def test_normal_reconcile_cannot_discard_gap_before_catchup_on_wake(
    session, session_factory, settings, tmp_archive, monkeypatch
):
    from signals.ingest import jobs_insider
    from signals.ingest.indexes import ReconcileResult

    yesterday = NOW.date() - timedelta(days=1)
    last = yesterday - timedelta(days=90)
    set_state(session, "reconcile_last_day", {"day": last.isoformat()})
    seen = []

    def reconcile(client, factory, day, **kwargs):
        seen.append(day)
        return ReconcileResult(day, 0, 0, 0, 0)

    monkeypatch.setattr(jobs_insider, "reconcile_day", reconcile)
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        None,
        {},
        {},
        lambda p: None,
        lambda: NOW,
    )
    jobs_insider.reconcile_daily(ctx)
    from signals.catchup import find_missed

    monkeypatch.setattr(
        jobs,
        "load_all_jobs",
        lambda: {
            "reconcile_daily": JobSpec(
                "reconcile_daily", lambda ctx: {}, cron={"hour": 6, "minute": 30}
            )
        },
    )
    session.add(
        IngestRun(
            job="reconcile_daily", started_at=NOW - timedelta(minutes=1), finished_at=NOW, errors=0
        )
    )
    session.flush()
    assert find_missed(session, NOW) == ["reconcile_daily"]
    ctx.params["catch_up"] = True
    jobs_insider.reconcile_daily(ctx)
    expected = [
        last + timedelta(days=n)
        for n in range(1, 91)
        if is_sec_business_day(last + timedelta(days=n))
    ]
    assert set(seen) == set(expected)


def test_busy_requested_job_requeues_without_starving_later_work(
    session, session_factory, settings, tmp_archive, monkeypatch
):
    from signals.jobs import run_request

    isolated_specs(monkeypatch, ["prices_daily"])
    session.add(
        IngestRun(job="prices_daily", started_at=NOW - timedelta(minutes=2), finished_at=None)
    )
    req = JobRequest(
        kind="prices_daily", status="running", requested_at=NOW - timedelta(hours=1), started_at=NOW
    )
    session.add(req)
    session.flush()
    monkeypatch.setattr(jobs, "now_et", lambda: NOW)
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        req.id,
        {},
        {},
        lambda p: None,
    )
    run_request(lambda req: ctx, session_factory, req.id)
    session.refresh(req)
    assert req.status == "requested" and req.started_at is None and req.finished_at is None
    assert req.requested_at == NOW
