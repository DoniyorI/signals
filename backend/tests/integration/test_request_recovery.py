"""Restart and documented re-request paths preserve resumable backfill checkpoints."""

from datetime import datetime

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from signals import cli, jobs
from signals.api.queries.health import _job_statuses
from signals.db.models import IngestRun, JobRequest
from signals.domain.calendars import ET
from signals.ingest import jobs_insider
from signals.ingest.feed import PollResult
from signals.jobs import BACKFILL_STEPS, JobSpec, request_job, track_run
from signals.sec.client import SecClient
from tests.support import MockRouter


def _execute_requested(session, session_factory, settings, archive, kind, params=None):
    rid = request_job(session, kind, params)
    claimed = jobs.claim_next_request(session)
    assert claimed is not None and claimed.id == rid
    claimed.progress = {"checkpoint": {"offset": 200}}
    session.flush()
    sec = SecClient(settings, http=MockRouter({}).client)
    builder = jobs.make_ctx_builder(settings, session_factory, sec, archive)

    def build(req):
        ctx = builder(req)
        ctx.now = lambda: datetime(2024, 6, 3, 10, 0, tzinfo=ET)
        return ctx

    jobs.run_request(build, session_factory, rid)
    session.expire_all()
    return session.get(JobRequest, rid)


def test_requested_live_poll_errors_are_health_visible_and_keep_result(
    session,
    session_factory,
    settings,
    tmp_archive,
    monkeypatch,
):
    message = "0002000001-24-000001: ValueError: bad ownership XML"
    poll = PollResult(1, 2, 1, 1, frozenset(), frozenset(), frozenset(), (message,))
    monkeypatch.setattr(jobs_insider, "poll_feed", lambda *a, **kw: poll)
    row = _execute_requested(session, session_factory, settings, tmp_archive, "live_poll")
    assert row.status == "failed" and message in row.error
    assert row.progress["result"]["new"] == 1
    assert row.progress["result"]["errors"] == 1
    assert row.progress["result"]["error_details"] == [message]
    assert row.progress["checkpoint"] == {"offset": 200}
    status = next(item for item in _job_statuses(session) if item.kind == "live_poll")
    assert status.last_status == "failed" and status.last_error == row.error


def test_requested_reparse_missing_archive_fails_with_accession_diagnostic(
    session,
    session_factory,
    settings,
    tmp_archive,
):
    accession = "0002000001-24-000001"
    row = _execute_requested(
        session, session_factory, settings, tmp_archive, "reparse", {"accessions": [accession]}
    )
    assert row.status == "failed"
    assert accession in row.error and "no raw archive" in row.error
    assert row.progress["result"]["parsed"] == 0
    assert row.progress["result"]["error"] == 1
    assert row.progress["checkpoint"] == {"offset": 200}


def test_requested_nested_error_counter_fails_without_losing_results(
    session,
    session_factory,
    settings,
    tmp_archive,
    monkeypatch,
):
    result = {"results": [{"errors": 2, "new": 3}], "days": ["2024-06-03"]}
    monkeypatch.setitem(jobs.JOBS, "partial_demo", JobSpec("partial_demo", lambda ctx: result))
    row = _execute_requested(session, session_factory, settings, tmp_archive, "partial_demo")
    assert row.status == "failed" and "2 errors" in row.error
    assert row.progress["result"] == result


def test_requested_numeric_nonerror_counters_remain_successful(
    session,
    session_factory,
    settings,
    tmp_archive,
    monkeypatch,
):
    result = {"errors": 0, "error": 0, "missing": 3, "rows": 100, "new": 5, "fetched": 7}
    monkeypatch.setitem(jobs.JOBS, "count_demo", JobSpec("count_demo", lambda ctx: result))
    row = _execute_requested(session, session_factory, settings, tmp_archive, "count_demo")
    assert row.status == "done" and row.error is None
    assert row.progress["result"] == result


def test_exclusive_worker_startup_requeues_all_interrupted_requests(session):
    rows = [
        JobRequest(
            kind="backfill_all",
            status="running",
            params={},
            progress={
                "done_steps": ["backfill_reference"],
                "steps": {"backfill_insiders": {"offset": 200}},
            },
        ),
        JobRequest(
            kind="backfill_funds", status="running", params={}, progress={"datasets_done": ["q1"]}
        ),
        JobRequest(
            kind="reparse",
            status="running",
            params={"accessions": ["0002000001-24-000001"]},
            progress={"n": 1},
        ),
        JobRequest(
            kind="analytics_incremental",
            status="running",
            params={"issuer_ciks": [1000001]},
            progress={"phase": "decisions"},
        ),
        JobRequest(kind="backfill_prices", status="done", params={}, progress={}),
        JobRequest(kind="reparse", status="failed", params={}, progress={}, error="bad XML"),
    ]
    session.add_all(rows)
    session.flush()
    before = rows[0].progress.copy()
    assert jobs.recover_interrupted_requests(session) == 4
    assert rows[0].status == rows[1].status == "requested"
    assert rows[0].progress == before
    assert rows[2].status == rows[3].status == "requested"
    assert rows[2].params == {"accessions": ["0002000001-24-000001"]}
    assert rows[2].progress == {"n": 1}
    assert rows[3].params == {"issuer_ciks": [1000001]}
    assert rows[3].progress == {"phase": "decisions"}
    assert rows[4].status == "done" and rows[5].status == "failed"
    assert rows[5].error == "bad XML"
    claimed = jobs.claim_next_request(session)
    assert claimed is not None and claimed.id == rows[0].id


def test_backfill_retry_requires_matching_parameters_and_preserves_progress(session):
    checkpoint = {"datasets_done": ["q1"], "gap_fill_stakes": {"current": {"offset": 200}}}
    failed = JobRequest(
        kind="backfill_funds",
        status="failed",
        params={"year": 2020},
        progress=checkpoint,
        error="fetch failed",
        started_at=datetime(2024, 1, 1, tzinfo=ET),
        finished_at=datetime(2024, 1, 2, tzinfo=ET),
    )
    unrelated = JobRequest(kind="reparse", status="failed", params={}, progress={"n": 10})
    session.add_all([failed, unrelated])
    session.flush()
    different = request_job(session, "backfill_funds", {"year": 2021})
    assert different != failed.id
    retried = request_job(session, "backfill_funds", {"year": 2020})
    assert retried == failed.id
    assert failed.status == "requested" and failed.progress == checkpoint
    assert failed.error is failed.started_at is failed.finished_at is None
    assert request_job(session, "reparse") != unrelated.id


def test_running_identical_backfill_is_not_duplicated(session):
    running = JobRequest(
        kind="backfill_all",
        status="running",
        params={"scope": "all"},
        progress={"done_steps": ["backfill_reference"]},
    )
    session.add(running)
    session.flush()
    assert request_job(session, "backfill_all", {"scope": "all"}) == running.id
    assert request_job(session, "backfill_all", {"scope": "new"}) != running.id


def test_cli_retry_skips_finished_steps_and_resumes_child_checkpoint(
    session,
    session_factory,
    settings,
    tmp_archive,
    monkeypatch,
):
    calls = []
    attempt = 0
    for kind in BACKFILL_STEPS:
        monkeypatch.setitem(
            jobs.JOBS, kind, JobSpec(kind, lambda ctx, k=kind: calls.append(k) or {})
        )

    def resumable(ctx):
        nonlocal attempt
        attempt += 1
        calls.append(("insiders", ctx.progress.get("offset", 0)))
        if attempt == 1:
            ctx.progress["offset"] = 200
            ctx.save_progress(ctx.progress)
            raise RuntimeError("interrupted fetch")
        return {"parsed": 1}

    monkeypatch.setitem(jobs.JOBS, "backfill_insiders", JobSpec("backfill_insiders", resumable))
    monkeypatch.setattr(cli, "_session_factory", lambda: session_factory)
    monkeypatch.setattr(cli, "load_all_jobs", lambda: jobs.JOBS)
    sec = SecClient(settings, http=MockRouter({}).client)

    def builder(req):
        return jobs.JobContext(
            settings,
            session_factory,
            sec,
            tmp_archive,
            req.id,
            req.params,
            dict(req.progress),
            lambda p: jobs._save_progress(session_factory, req.id, p),
        )

    rid = request_job(session, "backfill_all")
    jobs.claim_next_request(session)
    jobs.run_request(builder, session_factory, rid)
    session.expire_all()
    assert session.get(JobRequest, rid).status == "failed"
    retry = CliRunner().invoke(cli.app, ["jobs", "request", "backfill_all"])
    assert retry.exit_code == 0, retry.output
    assert retry.output.startswith(f"{rid}\t")
    claimed = jobs.claim_next_request(session)
    assert claimed is not None and claimed.id == rid
    jobs.run_request(builder, session_factory, rid)
    session.expire_all()
    row = session.get(JobRequest, rid)
    assert row.status == "done"
    assert calls.count("backfill_reference") == 1
    assert ("insiders", 200) in calls
    assert datetime.fromisoformat(row.progress["updated_at"])
    assert datetime.fromisoformat(row.progress["steps"]["backfill_insiders"]["updated_at"])


def test_nested_same_job_tracking_reuses_tracker_and_records_one_run(session, session_factory):
    with track_run(session_factory, "analytics_full") as outer:
        outer.fetched = 2
        with track_run(session_factory, "analytics_full") as inner:
            assert inner is outer
            inner.new_rows += 3
        with track_run(session_factory, "different_job") as other:
            other.fetched = 9
    rows = session.scalars(select(IngestRun).order_by(IngestRun.id)).all()
    assert len(rows) == 2
    analytics = next(row for row in rows if row.job == "analytics_full")
    assert (analytics.fetched, analytics.new_rows) == (2, 3)


def test_nested_tracker_error_is_recorded_once_and_context_is_reset(session, session_factory):
    with (
        pytest.raises(ValueError),
        track_run(session_factory, "poll"),
        track_run(session_factory, "poll"),
    ):
        raise ValueError("bad filing")
    with track_run(session_factory, "poll") as fresh:
        assert fresh.errors == 0
    rows = session.scalars(select(IngestRun).order_by(IngestRun.id)).all()
    assert [row.errors for row in rows] == [1, 0]
    assert "bad filing" in rows[0].notes["exception"]
