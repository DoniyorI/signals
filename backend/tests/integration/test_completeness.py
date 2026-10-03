"""Completeness uses archived SEC baselines and real isolated Postgres state."""

from datetime import date, datetime
from importlib import import_module

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from signals.api.deps import get_db
from signals.api.main import create_app
from signals.db.models import AppState, IngestRun, JobRequest
from signals.domain.accession import filing_txt_url
from signals.domain.appstate import get_state, set_state
from signals.domain.calendars import ET
from signals.ingest.gap_fill import gap_fill
from signals.ingest.indexes import full_index_url
from signals.jobs import JobContext
from signals.sec.client import SecClient, SecNotFoundError
from signals.sec.ratelimit import TokenBucket
from tests.factories import (
    make_decision,
    make_decision_return,
    make_filing,
    make_fund_filing,
    make_fund_manager,
    make_issuer,
    make_prices,
    make_transaction,
)
from tests.integration.insider_support import idx_line, idx_text
from tests.support import MockRouter


def _module():
    return import_module("signals.completeness")


def _client(settings, routes):
    router = MockRouter(routes)
    sec = SecClient(
        settings,
        http=router.client,
        sleep=lambda _: None,
        limiter=TokenBucket(rate=10000, capacity=10000),
    )
    return sec, router


def _index(form="4", day="2025-01-10", n=100):
    return idx_text(
        [
            idx_line(
                form_type=form,
                company="Test",
                cik=1000001,
                date_filed=day,
                accession=f"0001000001-25-{i:06d}",
            )
            for i in range(n)
        ]
    ).encode()


def _row(report, year, quarter, family):
    return next(
        row
        for row in report.quarters
        if (row.year, row.quarter, row.family) == (year, quarter, family)
    )


def _baseline(session, settings, tmp_archive, body=None, *, year=2025, quarter=1, as_of=None):
    sec, router = _client(settings, {full_index_url(year, quarter): body or _index()})
    counts = _module().index_counts(
        session, sec, tmp_archive, year, quarter, settings=settings, as_of=as_of
    )
    return counts, router


def _ctx(settings, session_factory, tmp_archive, sec, as_of=date(2025, 4, 2)):
    return JobContext(
        settings,
        session_factory,
        sec,
        tmp_archive,
        None,
        {},
        {},
        lambda _: None,
        now=lambda: datetime.combine(as_of, datetime.min.time(), ET),
    )


def test_completeness_endpoint_is_read_only(session, settings, monkeypatch):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session

    def external_forbidden(*args, **kwargs):
        pytest.fail("API must not fetch SEC or price services")

    monkeypatch.setattr(SecClient, "get", external_forbidden)
    monkeypatch.setattr(_module(), "get_settings", lambda: settings)
    before = session.scalar(select(func.count()).select_from(AppState))
    response = TestClient(app).get("/api/health/completeness?as_of=2025-04-02")
    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == "2025-04-02"
    assert body["checked_at"] is None
    assert body["returns"]["filed"]["pct"] is None
    assert session.scalar(select(func.count()).select_from(AppState)) == before


def test_index_counts_by_family(session, settings, tmp_archive, fixture_bytes, manifest):
    counts, router = _baseline(session, settings, tmp_archive, fixture_bytes("full_index"))
    assert counts == manifest["full_index"]["expect"]["family_accession_counts"]
    assert [str(request.url) for request in router.requests] == [full_index_url(2025, 1)]
    assert tmp_archive.get("full_index", "2025Q1", "idx") == fixture_bytes("full_index")


def test_index_counts_include_amendments_and_unique_accessions(session, settings, tmp_archive):
    forms = ["3/A", "4", "5/A", "144/A", "SCHEDULE 13D/A", "SCHEDULE 13G", "13F-NT/A"]
    lines = [
        idx_line(
            form_type=form,
            company="Test",
            cik=1,
            date_filed="2025-01-10",
            accession=f"0000000001-25-{i:06d}",
        )
        for i, form in enumerate(forms)
    ]
    counts, _ = _baseline(session, settings, tmp_archive, idx_text([*lines, lines[0]]).encode())
    assert counts == {"ownership": 3, "form144": 1, "stakes": 2, "13f": 1}


def test_stored_counts_by_filed_date_and_family(session):
    for i, form in enumerate(["3", "4/A", "5", "144/A", "SCHEDULE 13G/A", "13F-NT/A"]):
        make_filing(session, accession_no=f"count-{i}", form_type=form, filed_date=date(2025, 1, 1))
    make_filing(session, accession_no="outside", filed_date=date(2025, 4, 1))
    assert _module().stored_counts(session, 2025, 1) == {
        "ownership": 3,
        "form144": 1,
        "stakes": 1,
        "13f": 1,
    }


def test_quarter_below_threshold_is_gap(session, settings, tmp_archive):
    _baseline(session, settings, tmp_archive)
    for i in range(99):
        make_filing(session, accession_no=f"0001000001-25-{i:06d}", filed_date=date(2025, 1, 10))
    report = _module().completeness_report(session, as_of=date(2025, 4, 2), settings=settings)
    row = _row(report, 2025, 1, "ownership")
    assert (row.indexed, row.stored, row.pct, row.status) == (100, 99, 0.99, "gap")
    assert _row(report, 2025, 1, "13f").status == "complete"


def test_unknown_baseline_never_implies_complete(session, settings):
    report = _module().completeness_report(session, as_of=date(2025, 4, 2), settings=settings)
    row = _row(report, 2016, 1, "ownership")
    assert (row.indexed, row.pct, row.status) == (None, None, "unknown")
    current = _row(report, 2025, 2, "ownership")
    assert (current.indexed, current.pct, current.status) == (None, None, "in_progress")


def test_current_quarter_in_progress_excludes_today(session, settings, tmp_archive):
    body = _index(day="2025-01-10", n=2) + _index(day="2025-01-11", n=1).split(b"\n")[-2] + b"\n"
    _baseline(session, settings, tmp_archive, body, as_of=date(2025, 1, 11))
    make_filing(session, accession_no="today", filed_date=date(2025, 1, 11))
    report = _module().completeness_report(session, as_of=date(2025, 1, 11), settings=settings)
    row = _row(report, 2025, 1, "ownership")
    assert (row.indexed, row.stored, row.status) == (2, 0, "in_progress")
    assert row.through == date(2025, 1, 10)


def test_historical_form_scope_does_not_create_false_gaps(session, settings, tmp_archive):
    body = idx_text(
        [
            idx_line(
                form_type="144", company="Old", cik=1, date_filed="2023-04-12", accession="old"
            ),
            idx_line(
                form_type="144", company="New", cik=1, date_filed="2023-04-13", accession="new"
            ),
        ]
    ).encode()
    _baseline(session, settings, tmp_archive, body, year=2023, quarter=2)
    make_filing(session, accession_no="new", form_type="144", filed_date=date(2023, 4, 13))
    report = _module().completeness_report(session, as_of=date(2025, 4, 2), settings=settings)
    row = _row(report, 2023, 2, "form144")
    assert (row.indexed, row.stored, row.status) == (1, 1, "complete")
    assert _row(report, 2023, 1, "form144").status == "not_supported"
    assert _row(report, 2024, 3, "stakes").status == "not_supported"


def test_missing_or_malformed_index_does_not_create_empty_baseline(session, settings, tmp_archive):
    sec, _ = _client(settings, {full_index_url(2025, 1): 404})
    with pytest.raises(SecNotFoundError):
        _module().index_counts(session, sec, tmp_archive, 2025, 1, settings=settings)
    sec, _ = _client(settings, {full_index_url(2025, 1): b"<html>Server error</html>"})
    with pytest.raises(ValueError, match="index"):
        _module().index_counts(session, sec, tmp_archive, 2025, 1, settings=settings)
    row = _row(
        _module().completeness_report(session, as_of=date(2025, 4, 2), settings=settings),
        2025,
        1,
        "ownership",
    )
    assert row.status == "unknown"


def test_gap_queues_gap_fill_once(session, session_factory, settings, tmp_archive):
    settings = settings.model_copy(update={"backfill_start": date(2025, 1, 1)})
    sec, _ = _client(
        settings,
        {full_index_url(2025, 1): _index(), full_index_url(2025, 2): idx_text([]).encode()},
    )
    ctx = _ctx(settings, session_factory, tmp_archive, sec)
    _module().completeness_check(ctx)
    _module().completeness_check(ctx)
    rows = session.scalars(select(JobRequest).where(JobRequest.kind == "gap_fill")).all()
    assert len(rows) == 1
    assert rows[0].params == {"family": "ownership", "year": 2025, "quarter": 1}
    rows[0].status = "running"
    session.flush()
    _module().completeness_check(ctx)
    assert session.scalar(select(func.count()).select_from(JobRequest)) == 1


def test_failed_gap_request_keeps_checkpoint(session, session_factory, settings, tmp_archive):
    settings = settings.model_copy(update={"backfill_start": date(2025, 1, 1)})
    sec, _ = _client(
        settings,
        {full_index_url(2025, 1): _index(), full_index_url(2025, 2): idx_text([]).encode()},
    )
    ctx = _ctx(settings, session_factory, tmp_archive, sec)
    _module().completeness_check(ctx)
    request = session.scalars(select(JobRequest).where(JobRequest.kind == "gap_fill")).one()
    request.status = "failed"
    request.progress = {"current": {"quarter": "2025Q1", "offset": 70}}
    session.flush()
    _module().completeness_check(ctx)
    session.refresh(request)
    assert request.status == "requested"
    assert request.progress == {"current": {"quarter": "2025Q1", "offset": 70}}


def test_unavailable_after_three_attempts(session, session_factory, settings, tmp_archive):
    acc = "0001000001-25-000000"
    sec, router = _client(
        settings, {full_index_url(2025, 1): _index(n=1), filing_txt_url(1000001, acc): 404}
    )
    progress = {}
    for _ in range(4):
        gap_fill(
            sec,
            session_factory,
            form_types=["4"],
            start=date(2025, 1, 1),
            end=date(2025, 3, 31),
            settings=settings,
            archive=tmp_archive,
            progress=progress,
            save_progress=lambda _: None,
        )
    fetched = [r for r in router.requests if str(r.url) == filing_txt_url(1000001, acc)]
    assert len(fetched) == 3
    report = _module().completeness_report(session, as_of=date(2025, 4, 2), settings=settings)
    assert [(row.accession_no, row.attempts) for row in report.unavailable] == [(acc, 3)]
    assert "404" in report.unavailable[0].error


def test_unavailable_only_gap_does_not_requeue(session, session_factory, settings, tmp_archive):
    settings = settings.model_copy(update={"backfill_start": date(2025, 1, 1)})
    sec, _ = _client(
        settings,
        {full_index_url(2025, 1): _index(n=1), full_index_url(2025, 2): idx_text([]).encode()},
    )
    for _ in range(3):
        gap_fill(
            sec,
            session_factory,
            form_types=["4"],
            start=date(2025, 1, 1),
            end=date(2025, 3, 31),
            settings=settings,
            archive=tmp_archive,
            progress={},
            save_progress=lambda _: None,
        )
    _module().completeness_check(_ctx(settings, session_factory, tmp_archive, sec))
    assert session.scalar(select(func.count()).select_from(JobRequest)) == 0


def test_returns_coverage_counts_both_bases(session, settings):
    first = make_decision(session)
    second = make_decision(session, first_trade_date=date(2024, 2, 12))
    make_decision(
        session,
        first_trade_date=date(2024, 12, 20),
        accepted_at=datetime(2024, 12, 20, 10, tzinfo=ET),
    )
    make_decision_return(session, first.id, basis="filed")
    make_decision_return(session, first.id, basis="executed")
    make_decision_return(session, second.id, basis="filed", is_complete=False)
    report = _module().completeness_report(session, as_of=date(2025, 1, 2), settings=settings)
    assert (
        report.returns.filed.eligible,
        report.returns.filed.covered,
        report.returns.filed.pct,
    ) == (2, 1, 0.5)
    assert (
        report.returns.executed.eligible,
        report.returns.executed.covered,
        report.returns.executed.pct,
    ) == (2, 1, 0.5)


def test_returns_maturity_respects_filing_time_and_entry_gap(session, settings):
    # 126 sessions from Jan 2 lands July 3 (early close). After its close targets July 5.
    first = make_decision(
        session, first_trade_date=date(2024, 1, 2), accepted_at=datetime(2024, 1, 2, 17, tzinfo=ET)
    )
    row = make_decision_return(session, first.id, basis="filed")
    row.entry_date = date(2024, 1, 8)
    report = _module().completeness_report(session, as_of=date(2024, 7, 5), settings=settings)
    assert report.returns.executed.eligible == 1
    assert report.returns.filed.eligible == 0


def test_price_coverage_requires_latest_session_and_actual_loading(session, settings):
    make_issuer(session)
    filing = make_filing(session)
    make_transaction(session, accession_no=filing.accession_no)
    make_prices(session, "ACME", date(2025, 1, 2), [10])
    make_prices(session, "SPY", date(2024, 12, 30), [10])
    report = _module().completeness_report(session, as_of=date(2025, 1, 3), settings=settings)
    assert (report.prices.total, report.prices.covered, report.prices.through) == (
        14,
        1,
        date(2025, 1, 2),
    )
    assert "SPY" in report.prices.missing_symbols and "ACME" not in report.prices.missing_symbols
    assert report.prices.loading is False
    parent = JobRequest(
        kind="backfill_all", status="running", progress={"done_steps": ["backfill_reference"]}
    )
    session.add(parent)
    session.flush()
    assert (
        _module()
        .completeness_report(session, as_of=date(2025, 1, 3), settings=settings)
        .prices.loading
        is True
    )
    parent.progress = {"done_steps": ["backfill_prices"]}
    session.flush()
    assert (
        _module()
        .completeness_report(session, as_of=date(2025, 1, 3), settings=settings)
        .prices.loading
        is False
    )
    session.add(IngestRun(job="prices_daily", started_at=datetime(2025, 1, 3, tzinfo=ET)))
    session.flush()
    assert (
        _module()
        .completeness_report(session, as_of=date(2025, 1, 3), settings=settings)
        .prices.loading
        is True
    )


def test_fund_coverage_by_report_period_and_deadline(session, settings):
    settings = settings.model_copy(update={"backfill_start": date(2024, 1, 1)})
    make_fund_manager(session, cik=3000001, is_tracked=True)
    make_fund_manager(session, cik=3000002, is_tracked=True)
    make_fund_filing(session, period=date(2024, 3, 31), filed_date=date(2024, 5, 15))
    report = _module().completeness_report(session, as_of=date(2024, 7, 2), settings=settings)
    assert (report.funds.tracked, report.funds.total, report.funds.covered, report.funds.pct) == (
        2,
        2,
        1,
        0.5,
    )
    assert [(row.cik, row.period, row.present) for row in report.funds.quarters] == [
        (3000001, date(2024, 3, 31), True),
        (3000002, date(2024, 3, 31), False),
    ]


def test_completeness_registered_last_backfill_step_and_weekly(settings):
    from signals.jobs import BACKFILL_STEPS, load_all_jobs
    from signals.worker import build_scheduler

    specs = load_all_jobs()
    assert BACKFILL_STEPS[-1] == "completeness_check"
    scheduled = build_scheduler(settings, specs=specs, ctx_factory=None).get_job(
        "completeness_check"
    )
    assert scheduled is not None
    assert scheduled.trigger.get_next_fire_time(None, datetime(2025, 1, 4, tzinfo=ET)) == datetime(
        2025, 1, 5, 6, tzinfo=ET
    )


def test_header_only_closed_index_is_unknown(session, settings, tmp_archive):
    sec, _ = _client(settings, {full_index_url(2025, 1): idx_text([]).encode()})
    with pytest.raises(ValueError, match="index"):
        _module().index_counts(session, sec, tmp_archive, 2025, 1, settings=settings)
    assert (
        _row(
            _module().completeness_report(session, as_of=date(2025, 4, 2), settings=settings),
            2025,
            1,
            "ownership",
        ).status
        == "unknown"
    )


def test_bad_index_row_does_not_silently_lower_baseline(session, settings, tmp_archive):
    body = _index(n=1) + b"4  truncated row\n"
    sec, _ = _client(settings, {full_index_url(2025, 1): body})
    with pytest.raises(ValueError, match="index"):
        _module().index_counts(session, sec, tmp_archive, 2025, 1, settings=settings)


def test_pending_or_failed_parse_is_still_a_gap(session, session_factory, settings, tmp_archive):
    settings = settings.model_copy(update={"backfill_start": date(2025, 1, 1)})
    for i, status in enumerate(["parsed", "pending", "error", "skipped"]):
        make_filing(
            session,
            accession_no=f"0001000001-25-{i:06d}",
            filed_date=date(2025, 1, 10),
            parse_status=status,
        )
    sec, _ = _client(
        settings,
        {full_index_url(2025, 1): _index(n=4), full_index_url(2025, 2): idx_text([]).encode()},
    )
    _module().completeness_check(_ctx(settings, session_factory, tmp_archive, sec))
    row = _row(
        _module().completeness_report(session, as_of=date(2025, 4, 2), settings=settings),
        2025,
        1,
        "ownership",
    )
    assert (row.stored, row.indexed, row.status) == (1, 4, "gap")
    assert session.scalar(select(func.count()).select_from(JobRequest)) == 1


def test_unindexed_accessions_cannot_hide_two_missing_filings(
    session, session_factory, settings, tmp_archive
):
    settings = settings.model_copy(update={"backfill_start": date(2025, 1, 1)})
    for i in range(98):
        make_filing(session, accession_no=f"0001000001-25-{i:06d}", filed_date=date(2025, 1, 10))
    for acc in ["unexpected-a", "unexpected-b"]:
        make_filing(session, accession_no=acc, filed_date=date(2025, 1, 10))
    sec, _ = _client(
        settings,
        {full_index_url(2025, 1): _index(), full_index_url(2025, 2): idx_text([]).encode()},
    )
    _module().completeness_check(_ctx(settings, session_factory, tmp_archive, sec))
    row = _row(
        _module().completeness_report(session, as_of=date(2025, 4, 2), settings=settings),
        2025,
        1,
        "ownership",
    )
    assert (row.stored, row.indexed, row.status) == (98, 100, "gap")
    assert session.scalar(select(func.count()).select_from(JobRequest)) == 1


def test_future_return_exit_not_covered_at_past_as_of(session, settings):
    decision = make_decision(session)
    row = make_decision_return(session, decision.id)
    row.exit_date = date(2025, 1, 10)
    report = _module().completeness_report(session, as_of=date(2025, 1, 3), settings=settings)
    assert (report.returns.filed.eligible, report.returns.filed.covered) == (1, 0)


def test_future_fund_position_does_not_change_past_price_universe(session, settings):
    from tests.factories import make_fund_position, make_security

    make_fund_manager(session, is_tracked=True)
    filing = make_fund_filing(session, filed_date=date(2025, 2, 15))
    make_security(session, ticker="FUTURE", issuer_cik=None)
    make_fund_position(session, accession_no=filing.accession_no)
    report = _module().completeness_report(session, as_of=date(2025, 1, 3), settings=settings)
    assert report.prices.total == 13
    assert "FUTURE" not in report.prices.missing_symbols


def test_indexed_zero_family_has_null_percentage(session, settings, tmp_archive):
    _baseline(session, settings, tmp_archive)
    row = _row(
        _module().completeness_report(session, as_of=date(2025, 4, 2), settings=settings),
        2025,
        1,
        "13f",
    )
    assert row.indexed == 0 and row.pct is None and row.status == "complete"


def test_manual_reparse_resolves_unavailable_diagnostic(session, settings):
    for _ in range(3):
        _module().record_accession_failure(
            session,
            accession="reparsed",
            cik=1,
            family="ownership",
            day=date(2025, 1, 10),
            error="bad XML",
        )
    assert len(_module().unavailable_accessions(session)) == 1
    make_filing(
        session, accession_no="reparsed", filed_date=date(2025, 1, 10), parse_status="parsed"
    )
    assert _module().unavailable_accessions(session) == []


@pytest.mark.parametrize("counts", [(1, 0), (0, 1)])
def test_cached_completeness_summary_warns_health(session, monkeypatch, counts):
    from signals.api.queries import health

    now = datetime(2025, 4, 2, 10, tzinfo=ET)
    monkeypatch.setattr(health, "now", lambda: now)
    monkeypatch.setattr(health, "find_missed", lambda s, at: [])
    set_state(session, "live_poll_last_success", {"at": now.isoformat()})
    assert health.get_health(session).status == "ok"
    set_state(
        session,
        "completeness_summary",
        {"checked_at": now.isoformat(), "gaps": counts[0], "unavailable": counts[1]},
    )
    output = health.get_health(session)
    assert output.status == "warn"
    assert output.completeness is not None
    assert (output.completeness.gaps, output.completeness.unavailable) == counts


def test_gap_fill_job_refreshes_health_summary(session, session_factory, settings, tmp_archive):
    settings = settings.model_copy(update={"backfill_start": date(2025, 1, 1)})
    sec, _ = _client(
        settings,
        {full_index_url(2025, 1): _index(n=1), full_index_url(2025, 2): idx_text([]).encode()},
    )
    ctx = _ctx(settings, session_factory, tmp_archive, sec)
    _module().completeness_check(ctx)
    summary = get_state(session, "completeness_summary")
    assert summary is not None and (summary["gaps"], summary["unavailable"]) == (1, 0)
    for _ in range(3):
        request = session.scalars(select(JobRequest).where(JobRequest.kind == "gap_fill")).one()
        ctx.params = request.params
        ctx.progress = request.progress
        _module().gap_fill_job(ctx)
        request.progress = dict(ctx.progress)
        session.flush()
    summary = get_state(session, "completeness_summary")
    assert summary is not None and (summary["gaps"], summary["unavailable"]) == (1, 1)


def test_legacy_completed_backfill_does_not_claim_new_step_done(session):
    from signals.api.queries.health import _backfill_steps

    old_steps = [
        "backfill_reference",
        "backfill_insiders",
        "backfill_funds",
        "backfill_prices",
        "analytics_full",
    ]
    session.add(JobRequest(kind="backfill_all", status="done", progress={"done_steps": old_steps}))
    session.flush()
    steps = {row.step: row.status for row in _backfill_steps(session)}
    assert all(steps[step] == "done" for step in old_steps)
    assert steps["completeness_check"] == "pending"


@pytest.mark.parametrize("status", ["requested", "running"])
def test_historical_gap_fill_defers_catchup(
    session, session_factory, settings, tmp_archive, monkeypatch, status
):
    from signals import jobs
    from signals.catchup import catch_up
    from signals.jobs import JobSpec

    calls = []
    specs = {
        "analytics_full": JobSpec(
            "analytics_full", lambda ctx: calls.append("analytics") or {}, cron={"hour": 2}
        )
    }
    monkeypatch.setattr(jobs, "load_all_jobs", lambda: specs)
    session.add(
        JobRequest(
            kind="gap_fill",
            status=status,
            params={"family": "ownership", "year": 2025, "quarter": 1},
        )
    )
    session.flush()
    sec, _ = _client(settings, {})
    result = catch_up(_ctx(settings, session_factory, tmp_archive, sec))
    assert result.get("deferred") == "Historical backfill is active"
    assert calls == []
