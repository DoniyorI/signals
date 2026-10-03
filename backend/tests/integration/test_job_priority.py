"""Interactive insider refreshes run before safely resumable historical work."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from importlib import import_module
from threading import Barrier, Event

import httpx
import pytest
from sqlalchemy import delete, func, select, text

from signals import jobs
from signals.catchup import catch_up
from signals.db.models import FundFiling, IngestRun, JobRequest
from signals.db.session import make_session_factory, session_scope
from signals.domain.calendars import ET
from signals.ingest import jobs_funds
from signals.ingest.indexes import daily_index_url
from signals.jobs import JobContext, JobSpec
from signals.sec.client import SecClient
from tests.integration.insider_support import idx_text
from tests.integration.test_jobs_funds import LISTING_HTML, NEW_URL
from tests.support import MockRouter

REFRESH = "refresh_insider_performance"


def test_refresh_claim_precedes_older_historical_requests(session):
    historical = jobs.request_job(session, "backfill_all")
    priority = jobs.request_job(session, REFRESH, {"owner_cik": 1000001})
    claimed = jobs.claim_next_request(session)
    assert claimed is not None and claimed.id == priority
    claimed.status = "done"
    session.flush()
    next_request = jobs.claim_next_request(session)
    assert next_request is not None and next_request.id == historical


@pytest.mark.parametrize("status", ["requested", "running"])
def test_refresh_coalesces_only_matching_active_owner(session, status):
    first = JobRequest(kind=REFRESH, params={"owner_cik": 1000001}, status=status)
    session.add(first)
    session.flush()
    assert jobs.request_job(session, REFRESH, {"owner_cik": 1000001}) == first.id
    different = jobs.request_job(session, REFRESH, {"owner_cik": 1000002})
    assert different != first.id
    assert session.get(JobRequest, first.id).params == {"owner_cik": 1000001}
    assert session.get(JobRequest, different).params == {"owner_cik": 1000002}


def test_concurrent_refresh_requests_for_one_owner_share_request(db_engine):
    factory = make_session_factory(db_engine)
    ready = Barrier(2)
    owner = 999900001
    # Pause INSERT, after both unprotected SELECTs could see an empty queue. Advisory
    # serialization prevents the second SELECT until the first transaction commits.
    with db_engine.begin() as connection:
        connection.execute(
            text("""
            CREATE FUNCTION priority_request_insert_pause() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.kind = 'refresh_insider_performance' THEN PERFORM pg_sleep(0.15); END IF;
              RETURN NEW;
            END $$
        """)
        )
        connection.execute(
            text("""
            CREATE TRIGGER priority_request_insert_pause BEFORE INSERT ON job_requests
            FOR EACH ROW EXECUTE FUNCTION priority_request_insert_pause()
        """)
        )

    def enqueue():
        ready.wait(timeout=5)
        with session_scope(factory) as session:
            return jobs.request_job(session, REFRESH, {"owner_cik": owner})

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(enqueue) for _ in range(2)]
            ids = [future.result(timeout=5) for future in requests]
        assert ids[0] == ids[1]
        with session_scope(factory) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(JobRequest)
                    .where(
                        JobRequest.kind == REFRESH, JobRequest.params.contains({"owner_cik": owner})
                    )
                )
                == 1
            )
    finally:
        with db_engine.begin() as connection:
            connection.execute(text("DROP TRIGGER priority_request_insert_pause ON job_requests"))
            connection.execute(text("DROP FUNCTION priority_request_insert_pause()"))
        with session_scope(factory) as session:
            session.execute(
                delete(JobRequest).where(
                    JobRequest.kind == REFRESH, JobRequest.params.contains({"owner_cik": owner})
                )
            )


def _stub_fund_derivations(monkeypatch):
    monkeypatch.setattr(jobs_funds, "_apply_acceptance", lambda ctx: 0)
    monkeypatch.setattr(jobs_funds, "compute_fund_changes", lambda session: 0)
    monkeypatch.setattr(jobs_funds, "_openfigi_client", lambda ctx: None)
    monkeypatch.setattr(jobs_funds, "map_securities", lambda *args: None)
    monkeypatch.setattr(jobs_funds, "flag_value_unit_anomalies", lambda session: 0)
    monkeypatch.setattr(jobs_funds, "refresh_tracked_funds", lambda *args, **kwargs: 0)


def test_full_backfill_yields_after_committed_fund_dataset_and_resumes(
    session, session_factory, settings, tmp_archive, fixture_bytes, monkeypatch
):
    _stub_fund_derivations(monkeypatch)
    monkeypatch.setattr(jobs_funds, "_gap_fill", lambda *args, **kwargs: None)
    calls = []
    for kind in jobs.BACKFILL_STEPS:
        func_ = (
            jobs_funds.backfill_funds
            if kind == "backfill_funds"
            else (lambda ctx, kind=kind: calls.append(kind) or {})
        )
        monkeypatch.setitem(jobs.JOBS, kind, JobSpec(kind, func_))
    monkeypatch.setitem(
        jobs.JOBS, REFRESH, JobSpec(REFRESH, lambda ctx: calls.append(REFRESH) or {})
    )
    parent = JobRequest(
        kind="backfill_all",
        status="running",
        progress={
            "done_steps": ["backfill_reference", "backfill_insiders"],
            "steps": {
                "backfill_insiders": {"datasets_done": ["preserved"]},
                "backfill_funds": {"datasets_done": ["2016q1_form13f.zip"]},
            },
        },
    )
    session.add(parent)
    session.flush()

    def downloaded(request):
        with session_scope(session_factory) as connection:
            jobs.request_job(connection, REFRESH, {"owner_cik": 1000001})
        return httpx.Response(200, content=fixture_bytes("bulk_13f_slice_2025"))

    router = MockRouter({jobs_funds.LISTING_URL: LISTING_HTML.encode(), NEW_URL: downloaded})
    builder = jobs.make_ctx_builder(
        settings, session_factory, SecClient(settings, http=router.client), tmp_archive
    )
    jobs.run_request(builder, session_factory, parent.id)
    session.expire_all()
    assert parent.status == "requested" and parent.error is None
    assert parent.started_at is None and parent.finished_at is None
    assert parent.progress["done_steps"] == ["backfill_reference", "backfill_insiders"]
    assert parent.progress["steps"]["backfill_insiders"] == {"datasets_done": ["preserved"]}
    assert parent.progress["steps"]["backfill_funds"]["datasets_done"] == [
        "2016q1_form13f.zip",
        "2026q2_form13f.zip",
    ]
    assert session.scalar(select(func.count()).select_from(FundFiling)) > 0
    interrupted = session.scalars(select(IngestRun)).all()
    assert {row.job for row in interrupted} == {"backfill_all", "backfill_funds"}
    assert all(
        row.errors == 0 and row.finished_at is not None and row.notes.get("deferred")
        for row in interrupted
    )
    priority = jobs.claim_next_request(session)
    assert priority is not None and priority.kind == REFRESH
    jobs.run_request(builder, session_factory, priority.id)
    resumed = jobs.claim_next_request(session)
    assert resumed is not None and resumed.id == parent.id
    jobs.run_request(builder, session_factory, resumed.id)
    session.expire_all()
    assert parent.status == "done" and parent.error is None
    assert calls == [REFRESH, "backfill_prices", "analytics_full", "completeness_check"]
    assert [str(request.url) for request in router.requests].count(NEW_URL) == 1


def test_fund_gap_checkpoint_defers_and_preserves_completed_quarter(
    session, session_factory, settings, tmp_archive, monkeypatch
):
    _stub_fund_derivations(monkeypatch)
    monkeypatch.setattr(
        import_module("signals.ingest.gap_fill"),
        "now_et",
        lambda: datetime(2026, 7, 2, tzinfo=ET),
    )
    settings = settings.model_copy(update={"stakes_start": datetime(2026, 7, 3).date()})
    parent = JobRequest(
        kind="backfill_funds",
        status="running",
        progress={"datasets_done": ["2016q1_form13f.zip", "2026q2_form13f.zip"]},
    )
    session.add(parent)
    session.flush()
    index_url = daily_index_url(datetime(2026, 7, 1).date())

    def index(request):
        with session_scope(session_factory) as connection:
            jobs.request_job(connection, REFRESH, {"owner_cik": 1000001})
        return httpx.Response(200, content=idx_text([]).encode())

    router = MockRouter({jobs_funds.LISTING_URL: LISTING_HTML.encode(), index_url: index})
    builder = jobs.make_ctx_builder(
        settings, session_factory, SecClient(settings, http=router.client), tmp_archive
    )

    def build(req):
        ctx = builder(req)
        ctx.now = lambda: datetime(2026, 7, 2, tzinfo=ET)
        return ctx

    monkeypatch.setitem(
        jobs.JOBS, "backfill_funds", JobSpec("backfill_funds", jobs_funds.backfill_funds)
    )
    jobs.run_request(build, session_factory, parent.id)
    session.expire_all()
    assert parent.status == "requested" and parent.error is None
    assert parent.progress["gap_fill_funds"]["quarters_done"] == ["2026Q3"]
    assert parent.progress["gap_fill_funds"]["pending_failures"] == {}
    run = session.scalars(select(IngestRun)).one()
    assert run.errors == 0 and run.notes.get("deferred")


def test_refresh_cannot_overlap_other_maintenance(db_engine, settings, tmp_archive):
    factory = make_session_factory(db_engine)
    entered, release = Event(), Event()

    def holding(ctx):
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
        lambda progress: None,
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(
                jobs.execute_job,
                JobSpec("priority_maintenance_probe", holding, cron={"hour": 2}),
                ctx,
            )
            try:
                assert entered.wait(5)
                with pytest.raises(jobs.JobAlreadyRunning):
                    jobs.execute_job(JobSpec(REFRESH, lambda ctx: {}), ctx)
            finally:
                release.set()
            running.result(timeout=5)
    finally:
        with session_scope(factory) as session:
            session.execute(
                delete(IngestRun).where(IngestRun.job.in_([REFRESH, "priority_maintenance_probe"]))
            )


@pytest.mark.parametrize("status", ["requested", "queued", "running"])
def test_startup_catchup_defers_for_insider_refresh_after_failed_backfill(
    session, session_factory, settings, tmp_archive, monkeypatch, status
):
    specs = {
        "reconcile_daily": JobSpec("reconcile_daily", lambda ctx: {}, cron={"hour": 2}),
        "analytics_full": JobSpec("analytics_full", lambda ctx: {}),
    }
    monkeypatch.setattr(jobs, "load_all_jobs", lambda: specs)
    session.add_all(
        [
            JobRequest(
                kind="backfill_all",
                status="failed",
                error="Invalid bulk ZIP",
                progress={"steps": {"backfill_funds": {"datasets_done": ["preserved"]}}},
            ),
            JobRequest(kind=REFRESH, status=status, params={"owner_cik": 1000001}),
        ]
    )
    session.flush()
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        None,
        {},
        {},
        lambda progress: None,
        lambda: datetime(2026, 7, 2, 12, tzinfo=ET),
    )
    result = catch_up(ctx)
    assert result["ran"] == [] and result["behind"] == ["reconcile_daily"]
    assert "queued" in result["deferred"]
    assert (
        session.scalar(
            select(func.count()).select_from(IngestRun).where(IngestRun.job == "reconcile_daily")
        )
        == 0
    )
