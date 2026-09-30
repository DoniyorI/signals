"""Production ingestion/worker checkpoints must be visible through the health contract."""

import io
import zipfile
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from signals import worker
from signals.api.queries import health
from signals.db.models import FeedItem, Filing, IngestRun, JobRequest
from signals.domain.accession import filing_txt_url
from signals.domain.calendars import ET
from signals.ingest import feed, pipeline
from signals.jobs import BACKFILL_STEPS, JobContext, JobSpec, track_run
from signals.reference import jobs as reference_jobs
from signals.sec.client import SecClient
from signals.worker import _run_scheduled
from tests.integration.insider_support import atom_entry, atom_feed, ownership_handler
from tests.support import MockRouter

NOW = datetime(2026, 9, 30, 10, 0, tzinfo=ET)


@pytest.fixture(autouse=True)
def frozen_health(monkeypatch):
    monkeypatch.setattr(health, "now", lambda: NOW)


@pytest.mark.parametrize("old_attempt", [None, NOW - timedelta(days=2)])
def test_pipeline_failure_updates_attempt_and_warns(
    session, settings, tmp_archive, fixture_bytes, monkeypatch, old_attempt
):
    raw = fixture_bytes("form4_buy_single")
    sgml = pipeline.SgmlFiling.from_txt(raw)
    if old_attempt is not None:
        session.add(
            Filing(
                accession_no=sgml.accession_no,
                form_type="4",
                primary_cik=sgml.primary_cik(),
                filed_date=sgml.filed_date,
                source="feed",
                parse_status="parsed",
                parsed_at=old_attempt,
            )
        )
        session.flush()

    def fail(*args):
        raise ValueError("bad ownership XML")

    monkeypatch.setattr(pipeline, "get_handler", lambda form: fail)
    monkeypatch.setattr(pipeline, "now_et", lambda: NOW)
    outcome = pipeline.ingest_raw(
        session,
        raw,
        source="feed",
        raw_path=None,
        first_seen_at=None,
        settings=settings,
        archive=tmp_archive,
    )
    assert outcome.status == "error"
    assert session.get(Filing, sgml.accession_no).parsed_at == NOW
    result = health.get_health(session)
    assert result.status == "warn"
    assert result.parse_errors[0].error == "ValueError: bad ownership XML"


def _ctx(settings, session_factory, tmp_archive, client=None):
    client = client or SecClient(settings, http=MockRouter({}).client, sleep=lambda _: None)
    return JobContext(
        settings,
        session_factory,
        client,
        tmp_archive,
        None,
        {},
        {},
        lambda _: None,
        now=lambda: NOW,
    )


def test_tracked_exception_message_reaches_health(session, session_factory):
    with pytest.raises(RuntimeError), track_run(session_factory, "analytics_full"):
        raise RuntimeError("analytics exploded")
    job = health.get_health(session).jobs[0]
    assert job.last_status == "error"
    assert job.last_error == "RuntimeError: analytics exploded"


def test_scheduled_failure_has_durable_run(session, session_factory, settings, tmp_archive):
    def fail(ctx):
        raise RuntimeError("provider unavailable")

    _run_scheduled(
        JobSpec("prices_daily", fail), lambda _: _ctx(settings, session_factory, tmp_archive)
    )()
    run = session.execute(select(IngestRun)).scalar_one()
    assert run.errors == 1
    assert run.finished_at is not None
    job = health.get_health(session).jobs[0]
    assert job.last_status == "error"
    assert job.last_error == "RuntimeError: provider unavailable"
    assert health.get_health(session).status == "warn"


def test_scheduled_partial_failure_counters_and_details_are_durable(
    session, session_factory, settings, tmp_archive
):
    def poll(ctx):
        return {
            "entries": 4,
            "new": 3,
            "errors": 1,
            "error_details": ["0001234567-26-000001: SEC fetch failed"],
        }

    _run_scheduled(
        JobSpec("live_poll", poll), lambda _: _ctx(settings, session_factory, tmp_archive)
    )()
    run = session.execute(select(IngestRun)).scalar_one()
    assert (run.fetched, run.new_rows, run.errors) == (4, 3, 1)
    job = health.get_health(session).jobs[0]
    assert job.last_status == "error"
    assert job.last_error is not None
    assert "0001234567-26-000001: SEC fetch failed" in job.last_error


def test_nested_scheduled_tracking_has_one_row_and_aggregates_day_results(
    session, session_factory, settings, tmp_archive
):
    def reconcile(ctx):
        for errors in [2, 1]:
            with track_run(ctx.session_factory, "reconcile_daily") as run:
                run.errors = errors
        return {
            "results": [
                {"listed": 3, "ingested": 1, "errors": 2},
                {"listed": 3, "ingested": 2, "errors": 1},
            ]
        }

    _run_scheduled(
        JobSpec("reconcile_daily", reconcile),
        lambda _: _ctx(settings, session_factory, tmp_archive),
    )()
    run = session.execute(select(IngestRun)).scalar_one()
    assert (run.fetched, run.new_rows, run.errors) == (6, 3, 3)
    assert health.get_health(session).jobs[0].last_error


def test_real_malformed_submissions_member_is_health_visible(
    session, session_factory, settings, tmp_archive, monkeypatch
):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("CIK0001234567.json", b"{bad json")
    router = MockRouter(
        {
            reference_jobs.SUBMISSIONS_URL: stream.getvalue(),
            reference_jobs.COMPANY_TICKERS_URL: (
                b'{"fields": ["cik", "name", "ticker", "exchange"], "data": []}'
            ),
        }
    )
    client = SecClient(settings, http=router.client, sleep=lambda _: None)
    monkeypatch.setattr(reference_jobs, "_frame_quarters", lambda *args, **kwargs: [])
    _run_scheduled(
        JobSpec("reference_refresh", reference_jobs.reference_refresh),
        lambda _: _ctx(settings, session_factory, tmp_archive, client),
    )()
    run = session.execute(select(IngestRun)).scalar_one()
    assert run.errors == 1
    job = health.get_health(session).jobs[0]
    assert job.last_status == "error"
    assert job.last_error


def test_backfill_all_flattens_actual_steps_and_gap_checkpoint(session):
    checkpoint = NOW - timedelta(minutes=1)
    session.add(
        JobRequest(
            kind="backfill_all",
            status="running",
            requested_at=NOW - timedelta(hours=1),
            started_at=NOW - timedelta(hours=1),
            progress={
                "updated_at": checkpoint.isoformat(),
                "done_steps": ["backfill_reference"],
                "steps": {
                    "backfill_reference": {"done": ["submissions", "company_tickers", "sectors"]},
                    "backfill_insiders": {
                        "datasets_done": ["2016q1", "2016q2"],
                        "gap_fill_144": {"current": {"quarter": "2026Q3", "offset": 7}},
                    },
                },
            },
        )
    )
    session.flush()
    steps = {step.step: step for step in health.get_health(session).backfill}
    assert set(BACKFILL_STEPS) <= steps.keys()
    assert "backfill_all" not in steps
    assert steps["backfill_reference"].status == "done"
    assert steps["backfill_reference"].done_units == 3
    assert steps["backfill_insiders"].status == "running"
    assert steps["backfill_insiders"].done_units == 2
    assert steps["backfill_insiders"].updated_at == checkpoint
    assert steps["backfill_prices"].status == "pending"
    gap = steps["backfill_insiders.gap_fill_144"]
    assert gap.done_units == 7 and gap.total_units is None


def test_reference_standalone_done_units_and_latest_parent_step_wins(session):
    session.add(
        JobRequest(
            kind="backfill_reference",
            status="done",
            requested_at=NOW - timedelta(days=1),
            progress={"done": ["submissions", "sectors"]},
        )
    )
    session.flush()
    standalone = health.get_health(session).backfill[0]
    assert standalone.done_units == 2
    session.add(
        JobRequest(
            kind="backfill_all",
            status="failed",
            requested_at=NOW,
            error="reference failed",
            progress={"steps": {"backfill_reference": {"done": ["submissions"]}}},
        )
    )
    session.flush()
    reference = next(
        step for step in health.get_health(session).backfill if step.step == "backfill_reference"
    )
    assert reference.done_units == 1 and reference.status == "failed"


def test_completed_quarter_does_not_mark_running_gap_step_done(session):
    session.add(
        JobRequest(
            kind="backfill_all",
            status="running",
            requested_at=NOW,
            progress={
                "done_steps": ["backfill_reference"],
                "steps": {"backfill_insiders": {"gap_fill_144": {"quarters_done": ["2026Q1"]}}},
            },
        )
    )
    session.flush()
    gap = next(
        step
        for step in health.get_health(session).backfill
        if step.step == "backfill_insiders.gap_fill_144"
    )
    assert gap.status == "running"


def test_latency_excludes_failed_skipped_and_invisible_filings(session):
    accepted = NOW - timedelta(minutes=5)
    for i, status in enumerate(["parsed", "error", "skipped", "parsed"]):
        accession = f"0001234567-26-00000{i}"
        session.add(
            Filing(
                accession_no=accession,
                form_type="4",
                primary_cik=1234567,
                filed_date=NOW.date(),
                source="feed",
                parse_status=status,
                accepted_at=accepted,
                first_seen_at=accepted + timedelta(seconds=30 if i == 0 else 200),
            )
        )
        if i != 3:
            session.add(FeedItem(accession_no=accession, form_type="4"))
    session.flush()
    result = health.get_health(session)
    assert result.feed_delay_p50_s == 30
    assert result.feed_delay_p95_s == 30
    assert result.last_filing_seen_at == accepted + timedelta(seconds=30)


def test_poll_latency_includes_fetch_parse_and_commit_time(
    session, session_factory, settings, tmp_archive, fixture_bytes, manifest, monkeypatch
):
    exp = manifest["form4_buy_single"]
    accepted = datetime.fromisoformat(exp["accepted_at"])
    start = accepted + timedelta(seconds=20)
    clock = [start]
    monkeypatch.setattr(feed, "now_et", lambda: clock[0], raising=False)
    monkeypatch.setattr(health, "now", lambda: clock[0])

    def fetch(request):
        clock[0] += timedelta(seconds=40)
        return httpx.Response(200, content=fixture_bytes("form4_buy_single"))

    def handle(session, sgml, filing, ctx):
        ownership_handler(session, sgml, filing, ctx)
        clock[0] += timedelta(seconds=50)

    monkeypatch.setattr(pipeline, "get_handler", lambda form: handle)
    body = atom_feed(
        [
            atom_entry(
                title=f"4 - Example Co ({exp['cik']:010d}) (Issuer)",
                term="4",
                accession=exp["accession"],
                cik=exp["cik"],
            )
        ]
    )
    router = MockRouter(
        {feed.feed_url("4", 0): body, filing_txt_url(exp["cik"], exp["accession"]): fetch}
    )
    client = SecClient(settings, http=router.client, sleep=lambda _: None)
    commit_delayed = [False]

    def commit_time(committed_session):
        if not committed_session.in_nested_transaction() and not commit_delayed[0]:
            clock[0] += timedelta(seconds=15)
            commit_delayed[0] = True

    event.listen(Session, "after_commit", commit_time)
    try:
        result = feed.poll_feed(
            client,
            session_factory,
            form_types=["4"],
            max_pages=1,
            now=start,
            settings=settings,
            archive=tmp_archive,
        )
    finally:
        event.remove(Session, "after_commit", commit_time)
    assert result.new == 1
    health_result = health.get_health(session)
    assert health_result.feed_delay_p95_s == 125
    assert health_result.last_filing_seen_at == accepted + timedelta(seconds=125)


def test_feed_entry_failures_keep_accession_diagnostics(
    session_factory, settings, tmp_archive, fixture_bytes, manifest
):
    exp = manifest["form4_buy_single"]
    body = atom_feed(
        [
            atom_entry(
                title=f"4 - Example Co ({exp['cik']:010d}) (Issuer)",
                term="4",
                accession=exp["accession"],
                cik=exp["cik"],
            )
        ]
    )
    router = MockRouter({feed.feed_url("4", 0): body})
    client = SecClient(settings, http=router.client, sleep=lambda _: None)
    result = feed.poll_feed(
        client,
        session_factory,
        form_types=["4"],
        max_pages=1,
        now=NOW,
        settings=settings,
        archive=tmp_archive,
    )
    assert result.errors == 1
    assert exp["accession"] in result.error_details[0]


def test_worker_startup_recovers_backfill_before_scheduler_runs(
    session, session_factory, settings, tmp_archive, monkeypatch, db_engine
):
    req = JobRequest(
        kind="backfill_all", status="running", progress={"done_steps": ["backfill_reference"]}
    )
    session.add(req)
    session.commit()
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "make_engine", lambda _: db_engine)
    monkeypatch.setattr(worker, "make_session_factory", lambda _: session_factory)
    monkeypatch.setattr(
        worker,
        "build_sec_client",
        lambda *args, **kwargs: _ctx(settings, session_factory, tmp_archive).sec,
    )

    def start(_scheduler):
        recovered = session.get(JobRequest, req.id, populate_existing=True)
        assert recovered.status == "requested"
        assert recovered.progress["done_steps"] == ["backfill_reference"]

    monkeypatch.setattr(worker.BlockingScheduler, "start", start)
    worker.main()


def test_worker_lock_refuses_second_worker_and_releases_on_exit(db_engine):
    with (
        worker.worker_lock(db_engine),
        pytest.raises(RuntimeError, match="already running"),
        worker.worker_lock(db_engine),
    ):
        pytest.fail("second worker acquired the singleton lock")
    with worker.worker_lock(db_engine):
        pass


def test_worker_lock_releases_after_worker_exception(db_engine):
    with pytest.raises(ValueError), worker.worker_lock(db_engine):
        raise ValueError("worker failed")
    with worker.worker_lock(db_engine):
        pass


def test_second_worker_cannot_build_client_or_recover_live_jobs(
    db_engine, session, settings, monkeypatch
):
    request = JobRequest(kind="backfill_all", status="running", progress={"done_steps": []})
    session.add(request)
    session.commit()
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "make_engine", lambda _: db_engine)

    def build_client(*args, **kwargs):
        pytest.fail("second worker built an outside client before acquiring ownership")

    monkeypatch.setattr(worker, "build_sec_client", build_client)
    with worker.worker_lock(db_engine), pytest.raises(RuntimeError, match="already running"):
        worker.main()
    session.refresh(request)
    assert request.status == "running"


def test_interrupted_unfinished_ingest_run_becomes_health_visible(session):
    session.add(
        IngestRun(
            job="live_poll",
            started_at=NOW - timedelta(hours=1),
            finished_at=None,
            errors=0,
            notes={"entries": 7},
        )
    )
    session.flush()
    assert worker.recover_unfinished_runs(session) == 1
    result = health.get_health(session)
    assert result.jobs[0].last_status == "error"
    assert result.jobs[0].last_finished_at is not None
    assert result.jobs[0].last_error is not None
    assert "interrupted" in result.jobs[0].last_error.lower()
    assert result.status == "warn"
    assert worker.recover_unfinished_runs(session) == 0


def test_worker_restores_sec_pause_before_scheduling(
    session, session_factory, settings, tmp_archive, monkeypatch
):
    from types import SimpleNamespace

    from signals.domain.appstate import set_state
    from signals.sec.client import SecBlockedError, SecClient
    from tests.support import MockRouter

    until = NOW + timedelta(minutes=10)
    set_state(session, "sec_blocked_until", {"until": until.isoformat()})
    session.flush()
    sec = SecClient(settings, http=MockRouter({}).client, archive=tmp_archive, clock=lambda: NOW)
    monkeypatch.setattr(worker, "build_sec_client", lambda *args, **kwargs: sec)
    monkeypatch.setattr(worker, "now_et", lambda: NOW)

    def scheduler(*args, ctx_factory, specs, **kwargs):
        ctx = ctx_factory(next(iter(specs.values())))
        with pytest.raises(SecBlockedError):
            ctx.sec.get("https://www.sec.gov/blocked-probe")
        assert ctx.sec.blocked_until == until
        return SimpleNamespace(start=lambda: None)

    monkeypatch.setattr(worker, "build_scheduler", scheduler)
    worker._serve_worker(settings, session_factory)
