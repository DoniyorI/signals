"""Failed attempted entries stay retryable rather than completing a historical quarter."""

from copy import deepcopy
from datetime import date, datetime, timedelta

import pytest

from signals import jobs
from signals.analytics.entries import filed_target
from signals.analytics.funds import load_fund_inputs
from signals.db.models import FeedItem, Filing, FilingAcceptance
from signals.domain.accession import filing_txt_url
from signals.domain.appstate import get_state
from signals.domain.calendars import ET
from signals.ingest import dispatch, jobs_funds, jobs_insider
from signals.ingest.feed import PollResult
from signals.ingest.gap_fill import gap_fill
from signals.ingest.indexes import full_index_url
from signals.jobs import JobContext
from signals.sec.client import SecClient
from tests.factories import make_filing, make_fund_filing, make_fund_position, make_security
from tests.integration.insider_support import idx_line, idx_text
from tests.support import MockRouter


def test_live_poll_result_preserves_per_filing_error_details(
    session_factory,
    settings,
    tmp_archive,
    monkeypatch,
):
    detail = "0002000001-24-000001: ValueError: malformed ownership XML"
    result = PollResult(1, 1, 0, 1, frozenset(), frozenset(), frozenset(), (detail,))
    monkeypatch.setattr(jobs_insider, "poll_feed", lambda *a, **kw: result)
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        None,
        {},
        {},
        lambda _: None,
        now=lambda: datetime(2024, 6, 3, 10, 0, tzinfo=ET),
    )
    output = jobs_insider.live_poll(ctx)
    assert output is not None and output["error_details"] == [detail]


@pytest.mark.parametrize("failure", ["fetch", "parse"])
def test_gap_retry_keeps_attempted_offset_until_failed_filing_succeeds(
    session,
    session_factory,
    settings,
    tmp_archive,
    fixture_bytes,
    manifest,
    failure,
):
    accession = manifest["form4_buy_single"]["accession"]
    from signals.sec.sgml import SgmlFiling

    sgml = SgmlFiling.from_txt(fixture_bytes("form4_buy_single"))
    year, quarter = sgml.filed_date.year, (sgml.filed_date.month - 1) // 3 + 1
    key = f"{year}Q{quarter}"
    index = idx_text(
        [
            idx_line(
                form_type="4",
                company="Fixture",
                cik=sgml.primary_cik(),
                date_filed=sgml.filed_date.isoformat(),
                accession=accession,
            )
        ]
    )
    from signals.domain.accession import filing_txt_url

    url = filing_txt_url(sgml.primary_cik(), accession)
    router = MockRouter(
        {
            full_index_url(year, quarter): index.encode(),
            url: 404 if failure == "fetch" else b"bad SGML",
        }
    )
    sec = SecClient(settings, http=router.client, sleep=lambda _: None)
    progress = {}
    saved = []

    def fill():
        return gap_fill(
            sec,
            session_factory,
            form_types=["4"],
            start=sgml.filed_date,
            end=sgml.filed_date,
            settings=settings,
            archive=tmp_archive,
            progress=progress,
            save_progress=lambda p: saved.append(deepcopy(p)),
        )

    first = fill()
    assert first.errors == 1
    assert key not in progress.get("quarters_done", [])
    assert progress["current"] == {"quarter": key, "offset": 1}
    assert accession in str(progress["pending_failures"])
    router.routes[url] = fixture_bytes("form4_buy_single")
    jobs.load_all_jobs()
    try:
        second = fill()
        assert second.ingested == 1 and second.errors == 0
        assert progress["quarters_done"] == [key]
        assert not progress.get("pending_failures")
        assert "current" not in progress
        session.expire_all()
        assert session.get(Filing, accession).parse_status == "parsed"
        assert len([r for r in router.requests if str(r.url) == url]) == 2
        from signals.domain.appstate import get_state

        state = get_state(session, "completeness_attempt:" + accession)
        assert state is not None and state["status"] == "resolved"
    finally:
        dispatch.reset_registry()


@pytest.mark.parametrize("kind", ["backfill_insiders", "backfill_funds"])
def test_parent_backfill_remains_failed_when_gap_has_unresolved_errors(
    session,
    session_factory,
    settings,
    tmp_archive,
    monkeypatch,
    kind,
):
    from signals.ingest.gap_fill import GapFillResult

    sec = SecClient(settings, http=MockRouter({}).client)
    ctx = JobContext(settings, session_factory, sec, tmp_archive, None, {}, {}, lambda _: None)
    if kind == "backfill_insiders":
        monkeypatch.setattr(jobs_insider, "_fetch_listing", lambda ctx: "")
        monkeypatch.setattr(jobs_insider, "gap_fill", lambda *a, **kw: GapFillResult(1, 0, 0, 1))
        func = jobs_insider.backfill_insiders
    else:
        monkeypatch.setattr(jobs_funds, "_fetch_datasets", lambda ctx: [])
        import importlib

        gap_module = importlib.import_module("signals.ingest.gap_fill")
        monkeypatch.setattr(gap_module, "gap_fill", lambda *a, **kw: GapFillResult(1, 0, 0, 1))
        func = jobs_funds.backfill_funds
    with pytest.raises(RuntimeError, match="unresolved"):
        func(ctx)


def test_fund_acceptance_repair_updates_analytics_clock(
    session, session_factory, settings, tmp_archive
):
    fund = make_fund_filing(session, accepted_at=None)
    make_security(session, issuer_cik=None)
    make_fund_position(session, accession_no=fund.accession_no)
    accession = fund.accession_no
    session.add(FeedItem(accession_no=accession, form_type="13F-HR", accepted_at=None))
    accepted = datetime(2024, 5, 15, 10, 0, tzinfo=ET)
    session.add(FilingAcceptance(accession_no=accession, accepted_at=accepted))
    session.flush()
    sec = SecClient(settings, http=MockRouter({}).client)
    ctx = JobContext(settings, session_factory, sec, tmp_archive, None, {}, {}, lambda _: None)
    assert jobs_funds._apply_acceptance(ctx) == 1
    session.expire_all()
    assert session.get(Filing, accession).accepted_at == accepted
    assert session.get(FeedItem, accession).accepted_at == accepted
    books = load_fund_inputs(session, fund.filer_cik).books
    assert books[0].accepted_at == accepted
    assert filed_target(books[0].accepted_at, books[0].filed_date) == (
        date(2024, 5, 15),
        "close",
        (),
    )
    assert jobs_funds._apply_acceptance(ctx) == 0


@pytest.mark.parametrize("legacy_pending", [False, True])
def test_duplicate_index_and_pending_rows_do_not_exhaust_retries_in_one_scan(
    session, session_factory, settings, tmp_archive, legacy_pending
):
    accession = "0001000001-25-000001"
    line = idx_line(
        form_type="4",
        company="Joint filer",
        cik=1000001,
        date_filed="2025-01-10",
        accession=accession,
    )
    url = filing_txt_url(1000001, accession)
    router = MockRouter({full_index_url(2025, 1): idx_text([line] * 3).encode(), url: 404})
    sec = SecClient(settings, http=router.client, sleep=lambda _: None)
    progress = {}
    if legacy_pending:
        progress = {
            "current": {"quarter": "2025Q1", "offset": 3},
            "pending_failures": {
                "2025Q1": [{"cik": 1000001, "accession_no": accession, "error": "404"}] * 3
            },
        }
    for run in range(1, 5):
        result = gap_fill(
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
        state = get_state(session, "completeness_attempt:" + accession)
        assert state is not None and state["attempts"] == min(run, 3)
        assert result.errors == (1 if run < 3 else 0)
        if run < 3:
            assert len(progress["pending_failures"]["2025Q1"]) == 1
            assert progress["current"]["offset"] == 3
        else:
            assert progress["quarters_done"] == ["2025Q1"]
            assert not progress.get("pending_failures")
    assert len([r for r in router.requests if str(r.url) == url]) == 3


@pytest.mark.parametrize("wrong_field", ["form_type", "filed_date"])
def test_gap_fill_repairs_parsed_filing_with_wrong_index_identity(
    session, session_factory, settings, tmp_archive, fixture_bytes, wrong_field
):
    from signals.sec.sgml import SgmlFiling

    raw = fixture_bytes("form4_buy_single")
    sgml = SgmlFiling.from_txt(raw)
    wrong = (
        {"form_type": "5"}
        if wrong_field == "form_type"
        else {"filed_date": sgml.filed_date + timedelta(days=1)}
    )
    make_filing(
        session,
        accession_no=sgml.accession_no,
        form_type=sgml.form_type,
        filed_date=sgml.filed_date,
    )
    filing = session.get(Filing, sgml.accession_no)
    assert filing is not None
    setattr(filing, wrong_field, wrong[wrong_field])
    session.flush()
    year, quarter = sgml.filed_date.year, (sgml.filed_date.month - 1) // 3 + 1
    url = filing_txt_url(sgml.primary_cik(), sgml.accession_no)
    index = idx_text(
        [
            idx_line(
                form_type=sgml.form_type,
                company="Fixture",
                cik=sgml.primary_cik(),
                date_filed=sgml.filed_date.isoformat(),
                accession=sgml.accession_no,
            )
        ]
    )
    router = MockRouter({full_index_url(year, quarter): index.encode(), url: raw})
    sec = SecClient(settings, http=router.client, sleep=lambda _: None)
    from signals.ingest.handlers.insider import handle_ownership

    dispatch.register_handler([sgml.form_type], handle_ownership)
    try:
        result = gap_fill(
            sec,
            session_factory,
            form_types=[sgml.form_type],
            start=sgml.filed_date,
            end=sgml.filed_date,
            settings=settings,
            archive=tmp_archive,
            progress={},
            save_progress=lambda _: None,
        )
    finally:
        dispatch.reset_registry()
    assert (result.ingested, result.errors) == (1, 0)
    session.expire_all()
    repaired = session.get(Filing, sgml.accession_no)
    assert repaired is not None
    assert (repaired.form_type, repaired.filed_date) == (sgml.form_type, sgml.filed_date)
    assert len([r for r in router.requests if str(r.url) == url]) == 1


def test_gap_rejects_submission_that_conflicts_with_sec_index_date(
    session, session_factory, settings, tmp_archive, fixture_bytes
):
    from signals.sec.sgml import SgmlFiling

    raw = fixture_bytes("form4_buy_single")
    sgml = SgmlFiling.from_txt(raw)
    indexed_day = sgml.filed_date + timedelta(days=1)
    year, quarter = indexed_day.year, (indexed_day.month - 1) // 3 + 1
    url = filing_txt_url(sgml.primary_cik(), sgml.accession_no)
    index = idx_text(
        [
            idx_line(
                form_type=sgml.form_type,
                company="Fixture",
                cik=sgml.primary_cik(),
                date_filed=indexed_day.isoformat(),
                accession=sgml.accession_no,
            )
        ]
    )
    router = MockRouter({full_index_url(year, quarter): index.encode(), url: raw})
    result = gap_fill(
        SecClient(settings, http=router.client, sleep=lambda _: None),
        session_factory,
        form_types=[sgml.form_type],
        start=indexed_day,
        end=indexed_day,
        settings=settings,
        archive=tmp_archive,
        progress={},
        save_progress=lambda _: None,
    )
    assert (result.ingested, result.errors) == (0, 1)
    assert session.get(Filing, sgml.accession_no) is None
    assert tmp_archive.get("filing", sgml.accession_no) == raw
    state = get_state(session, "completeness_attempt:" + sgml.accession_no)
    assert state is not None and "does not match the SEC index" in state["error"]
