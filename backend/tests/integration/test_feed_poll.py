from datetime import datetime

import pytest
from sqlalchemy import select

from signals.db.models import JobRequest
from signals.domain.calendars import ET
from signals.ingest import dispatch
from signals.ingest.feed import feed_url, parse_atom, poll_feed
from signals.sec.client import SecClient
from signals.sec.ratelimit import TokenBucket
from tests.factories import make_filing
from tests.integration.insider_support import atom_entry, atom_feed, register_ownership_handler
from tests.support import MockRouter

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=ET)


@pytest.fixture(autouse=True)
def ownership_handler():
    register_ownership_handler()
    yield
    dispatch.reset_registry()


def _client(settings, routes: dict) -> tuple[SecClient, MockRouter]:
    router = MockRouter(routes)
    # A high-capacity limiter: this module tests pagination/dedupe, not rate limiting
    # (that's covered by test_sec_client.py), and many of these tests fetch 40+ accessions.
    limiter = TokenBucket(rate=1000, capacity=1000)
    client = SecClient(settings, http=router.client, sleep=lambda s: None, limiter=limiter)
    return client, router


def test_parse_atom_fixture(fixture_bytes, manifest):
    entries = parse_atom(fixture_bytes("atom_form4_p1"))
    exp = manifest["atom_form4_p1"]["expect"]
    assert len(entries) == exp["n_entries"]
    first = entries[0]
    assert first.accession_no == exp["first"]["accession"]
    assert first.form_type == exp["first"]["form_type"]
    assert first.cik == exp["first"]["cik"]


def test_filters_prefix_matches(session_factory, settings, tmp_archive, fixture_bytes):
    body = fixture_bytes("atom_form4_424b2")
    other_forms = [e for e in parse_atom(body) if e.form_type not in ("4", "4/A")]
    assert other_forms  # sanity: the fixture really does carry non-"4" entries

    client, router = _client(settings, {feed_url("4", 0): body})
    poll_feed(
        client,
        session_factory,
        form_types=["4"],
        max_pages=1,
        now=NOW,
        settings=settings,
        archive=tmp_archive,
    )
    fetched = {str(r.url) for r in router.requests}
    for entry in other_forms:
        assert not any(entry.accession_no in url for url in fetched)


def test_poll_paginates_until_known_accession(
    session, session_factory, settings, tmp_archive, fixture_bytes
):
    p1, p2 = fixture_bytes("atom_form4_p1"), fixture_bytes("atom_form4_p2")
    known = [e for e in parse_atom(p2) if e.form_type == "4"][-1]
    make_filing(
        session, accession_no=known.accession_no, primary_cik=known.cik, owners=(known.cik,)
    )
    session.commit()

    client, router = _client(
        settings, {feed_url("4", 0): p1, feed_url("4", 100): p2, feed_url("4", 200): b""}
    )
    result = poll_feed(
        client,
        session_factory,
        form_types=["4"],
        max_pages=5,
        now=NOW,
        settings=settings,
        archive=tmp_archive,
    )

    assert result.pages == 2
    fetched = [str(r.url) for r in router.requests]
    assert not any("start=200" in url for url in fetched)
    assert not any(known.accession_no in url and url.endswith(".txt") for url in fetched)
    first_entry = parse_atom(p1)[0]
    assert sum(1 for url in fetched if url.endswith(f"{first_entry.accession_no}.txt")) == 1


def test_dedupes_reporting_and_issuer_entries(session_factory, settings, tmp_archive):
    accession = "0009999999-26-000001"
    body = atom_feed(
        [
            atom_entry(
                title="4 - Doe Jane (0001111111) (Reporting)",
                term="4",
                accession=accession,
                cik=1111111,
            ),
            atom_entry(
                title="4 - Acme Corp (0002222222) (Issuer)",
                term="4",
                accession=accession,
                cik=2222222,
            ),
        ]
    )
    client, router = _client(settings, {feed_url("4", 0): body})
    poll_feed(
        client,
        session_factory,
        form_types=["4"],
        max_pages=1,
        now=NOW,
        settings=settings,
        archive=tmp_archive,
    )
    txt_requests = [r for r in router.requests if str(r.url).endswith(".txt")]
    assert len(txt_requests) == 1


def test_requests_incremental_analytics(
    session, session_factory, settings, tmp_archive, fixture_bytes, manifest
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
    from signals.domain.accession import filing_txt_url

    client, _router = _client(
        settings,
        {
            feed_url("4", 0): body,
            filing_txt_url(exp["cik"], exp["accession"]): fixture_bytes("form4_buy_single"),
        },
    )
    result = poll_feed(
        client,
        session_factory,
        form_types=["4"],
        max_pages=1,
        now=NOW,
        settings=settings,
        archive=tmp_archive,
    )
    assert result.new == 1
    assert exp["expect"]["issuer_cik"] in result.issuer_ciks

    req = session.execute(
        select(JobRequest).where(JobRequest.kind == "analytics_incremental")
    ).scalar_one()
    assert exp["expect"]["issuer_cik"] in req.params["issuer_ciks"]
