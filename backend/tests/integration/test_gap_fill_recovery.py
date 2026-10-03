"""Failed attempted entries stay retryable rather than completing a historical quarter."""

from copy import deepcopy
from datetime import date, datetime

import pytest

from signals import jobs
from signals.analytics.entries import filed_target
from signals.analytics.funds import load_fund_inputs
from signals.db.models import FeedItem, Filing, FilingAcceptance
from signals.domain.calendars import ET
from signals.ingest import dispatch, jobs_funds, jobs_insider
from signals.ingest.feed import PollResult
from signals.ingest.gap_fill import gap_fill
from signals.ingest.indexes import full_index_url
from signals.jobs import JobContext
from signals.sec.client import SecClient
from tests.factories import make_fund_filing, make_fund_position, make_security
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
