from datetime import date

import pytest

from signals.ingest import dispatch
from signals.ingest.indexes import daily_index_url, parse_form_idx, reconcile_day
from signals.sec.client import SecClient
from signals.sec.ratelimit import TokenBucket
from tests.factories import make_filing
from tests.integration.insider_support import idx_line, idx_text, register_ownership_handler
from tests.support import MockRouter


@pytest.fixture(autouse=True)
def ownership_handler():
    register_ownership_handler()
    yield
    dispatch.reset_registry()


def _client(settings, routes: dict) -> tuple[SecClient, MockRouter]:
    router = MockRouter(routes)
    limiter = TokenBucket(rate=1000, capacity=1000)
    return SecClient(settings, http=router.client, sleep=lambda s: None, limiter=limiter), router


def test_parse_daily_index_fixture(fixture_bytes, manifest):
    text = fixture_bytes("daily_index").decode("utf-8", errors="replace")
    entries = parse_form_idx(text)
    exp = manifest["daily_index"]["expect"]
    assert len(entries) == exp["n_entries"]

    sample = exp["sample"]
    match = next(e for e in entries if e.accession_no == sample["accession"])
    assert match.form_type == sample["form_type"]
    assert match.cik == sample["cik"]
    assert match.date_filed == date(2026, 9, 25)

    spaced = exp["spaced_form_sample"]
    spaced_match = next(e for e in entries if e.accession_no == spaced["accession"])
    assert spaced_match.form_type == spaced["form_type"]
    assert spaced_match.cik == spaced["cik"]

    counts: dict[str, int] = {}
    for e in entries:
        counts[e.form_type] = counts.get(e.form_type, 0) + 1
    for form, expected_count in exp["form_counts"].items():
        assert counts.get(form) == expected_count


def test_parse_full_index_fixture_dashed_dates(fixture_bytes, manifest):
    text = fixture_bytes("full_index").decode("utf-8", errors="replace")
    entries = parse_form_idx(text)
    exp = manifest["full_index"]["expect"]
    assert len(entries) == exp["n_entries"]
    sample = exp["sample"]
    match = next(e for e in entries if e.accession_no == sample["accession"])
    assert match.form_type == sample["form_type"]
    assert match.cik == sample["cik"]
    assert match.date_filed == date(2025, 2, 14)
    assert all(isinstance(e.date_filed, date) for e in entries)


def test_reconcile_ingests_only_missing(
    session, session_factory, settings, tmp_archive, fixture_bytes
):
    day = date(2025, 3, 31)
    a = ("4", "Alpha Co", 1509261, "0000912282-25-000343")
    b = ("4", "Beta Co", 1789029, "0002003074-25-000007")
    c = ("4", "Gamma Co", 1528396, "0001528396-25-000101")
    text = idx_text(
        [
            idx_line(form_type=a[0], company=a[1], cik=a[2], date_filed="20250331", accession=a[3]),
            idx_line(form_type=b[0], company=b[1], cik=b[2], date_filed="20250331", accession=b[3]),
            idx_line(form_type=c[0], company=c[1], cik=c[2], date_filed="20250331", accession=c[3]),
        ]
    )
    make_filing(session, accession_no=a[3], primary_cik=a[2], owners=(a[2],))
    session.commit()

    from signals.domain.accession import filing_txt_url

    client, router = _client(
        settings,
        {
            daily_index_url(day): text.encode(),
            filing_txt_url(b[2], b[3]): fixture_bytes("form4_joint"),
            filing_txt_url(c[2], c[3]): fixture_bytes("form4_10b5_1_flag"),
        },
    )
    result = reconcile_day(client, session_factory, day, settings=settings, archive=tmp_archive)

    assert (result.listed, result.missing, result.ingested, result.errors) == (3, 2, 2, 0)
    txt_requests = [r for r in router.requests if str(r.url).endswith(".txt")]
    assert len(txt_requests) == 2


def test_reconcile_holiday_404(session_factory, settings, tmp_archive):
    day = date(2025, 12, 25)
    client, _router = _client(settings, {})  # nothing routed -> 404
    result = reconcile_day(client, session_factory, day, settings=settings, archive=tmp_archive)
    assert result.listed == 0
