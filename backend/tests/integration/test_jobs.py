from datetime import datetime

import pytest
from sqlalchemy import select

from signals import jobs
from signals.db.models import Filing, IngestRun, JobRequest, Owner
from signals.domain.calendars import now_et
from signals.ingest import dispatch
from signals.ingest.pipeline import ingest_raw
from signals.jobs import (
    BACKFILL_STEPS,
    JOBS,
    JobContext,
    JobSpec,
    claim_next_request,
    register_job,
    request_job,
    run_request,
    track_run,
)
from signals.sec.client import SecClient
from signals.worker import build_scheduler
from tests.support import MockRouter


@pytest.fixture(autouse=True)
def restore_jobs():
    saved = dict(JOBS)
    yield
    JOBS.clear()
    JOBS.update(saved)
    dispatch.reset_registry()


def _builder(settings, session_factory, archive):
    sec = SecClient(settings, http=MockRouter({}).client, sleep=lambda s: None)
    return jobs.make_ctx_builder(settings, session_factory, sec, archive)


def _run(session, session_factory, settings, archive, kind, params=None):
    rid = request_job(session, kind, params)
    claimed = claim_next_request(session)
    assert claimed is not None and claimed.id == rid and claimed.status == "running"
    session.flush()
    run_request(_builder(settings, session_factory, archive), session_factory, rid)
    session.expire_all()
    return session.get(JobRequest, rid)


def test_request_and_run_job(session, session_factory, settings, tmp_archive):
    register_job("demo")(lambda ctx: {"n": 1})
    req = _run(session, session_factory, settings, tmp_archive, "demo")
    assert req.status == "done" and req.progress["result"] == {"n": 1}
    assert req.finished_at is not None


def test_failed_job_records_error(session, session_factory, settings, tmp_archive):
    def boom(ctx):
        raise RuntimeError("x")

    register_job("demo_fail")(boom)
    req = _run(session, session_factory, settings, tmp_archive, "demo_fail")
    assert (req.status, req.error) == ("failed", "RuntimeError: x")


def test_coalesce_unions_list_params(session):
    a = request_job(session, "analytics_incremental", {"issuer_ciks": [1]})
    b = request_job(session, "analytics_incremental", {"issuer_ciks": [2]})
    rows = session.scalars(
        select(JobRequest).where(JobRequest.kind == "analytics_incremental")
    ).all()
    assert a == b and len(rows) == 1 and rows[0].params["issuer_ciks"] == [1, 2]


def test_track_run_writes_row_on_error(session, session_factory):
    with pytest.raises(RuntimeError), track_run(session_factory, "demo_run") as run:
        run.fetched = 3
        run.notes["stage"] = "fetch"
        raise RuntimeError("network down")
    row = session.scalars(select(IngestRun).where(IngestRun.job == "demo_run")).one()
    assert (row.fetched, row.errors) == (3, 1) and row.finished_at is not None
    assert row.notes["stage"] == "fetch" and "RuntimeError" in row.notes["exception"]


def test_backfill_all_runs_steps_in_order(session, session_factory, settings, tmp_archive):
    calls: list[str] = []
    for kind in BACKFILL_STEPS:
        register_job(kind)(lambda ctx, k=kind: calls.append(k) or {"ok": k})
    req = _run(session, session_factory, settings, tmp_archive, "backfill_all")
    assert req.status == "done" and calls == list(BACKFILL_STEPS)
    assert req.progress["done_steps"] == list(BACKFILL_STEPS)

    calls.clear()

    def fail(ctx):
        calls.append("backfill_funds")
        raise ValueError("stop here")

    register_job("backfill_funds")(fail)
    req = _run(session, session_factory, settings, tmp_archive, "backfill_all")
    assert req.status == "failed" and "stop here" in (req.error or "")
    assert calls == ["backfill_reference", "backfill_insiders", "backfill_funds"]


def test_reparse_job_by_status(
    session, session_factory, settings, tmp_archive, fixture_bytes, manifest
):
    acc = manifest["form4_buy_single"]["accession"]
    path = tmp_archive.put("filing", acc, fixture_bytes("form4_buy_single"))

    def boom(s, sg, f, c):
        raise ValueError("bad parser")

    def ok(s, sg, f, c):
        s.add(Owner(cik=999_999_002, name="Reparsed", owner_type="person"))
        s.flush()

    dispatch.register_handler(["4"], boom)
    out = ingest_raw(
        session,
        fixture_bytes("form4_buy_single"),
        source="feed",
        raw_path=str(path),
        first_seen_at=None,
        settings=settings,
        archive=tmp_archive,
    )
    assert out.status == "error"
    session.flush()
    dispatch.register_handler(["4"], ok)
    req = _run(session, session_factory, settings, tmp_archive, "reparse", {"status": "error"})
    assert req.status == "done" and req.progress["result"] == {"parsed": 1, "error": 0}
    assert session.get(Filing, acc).parse_status == "parsed"


def test_scheduler_uses_et_timezone(settings):
    spec = JobSpec(
        "nightly", lambda ctx: None, cron={"hour": 2, "minute": 0}, interval_seconds=None
    )
    every = JobSpec("often", lambda ctx: None, cron=None, interval_seconds=60)
    sched = build_scheduler(settings, specs={"nightly": spec, "often": every}, ctx_factory=None)
    nightly = sched.get_job("nightly")
    assert nightly is not None and str(nightly.trigger.timezone) == "America/New_York"
    assert sched.get_job("often") is not None and sched.get_job("poll_job_requests") is not None


def test_job_context_now_is_et():
    ctx = JobContext(None, lambda: None, None, None, None, {}, {}, lambda p: None, now_et)  # type: ignore[arg-type]
    assert isinstance(ctx.now(), datetime) and ctx.now().tzinfo is not None
