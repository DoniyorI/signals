from datetime import datetime

import pytest
from sqlalchemy import select

from signals.db.models import Filing, Owner
from signals.domain.accession import filing_txt_url
from signals.ingest import dispatch
from signals.ingest.pipeline import ingest_accession, ingest_raw, reparse_accession
from signals.sec.client import SecClient
from tests.factories import make_filing
from tests.support import MockRouter

KEY = "form4_buy_single"


@pytest.fixture(autouse=True)
def clean_registry():
    dispatch.reset_registry()
    yield
    dispatch.reset_registry()


def _add_owner(session, sgml, filing, ctx):
    session.add(Owner(cik=999_999_001, name="Handler Ran", owner_type="person"))
    session.flush()


def _boom(session, sgml, filing, ctx):
    _add_owner(session, sgml, filing, ctx)
    raise ValueError("boom")


def _raw(**kw):
    return dict(source="test", raw_path=None, first_seen_at=None, **kw)


def test_ingest_raw_runs_registered_handler(session, settings, tmp_archive, fixture_bytes, manifest):
    dispatch.register_handler(["4"], _add_owner)
    out = ingest_raw(session, fixture_bytes(KEY), settings=settings, archive=tmp_archive, **_raw())
    assert out.status == "parsed" and out.accession_no == manifest[KEY]["accession"]
    filing = session.get(Filing, out.accession_no)
    assert filing is not None and filing.parse_status == "parsed" and filing.parsed_at is not None
    assert filing.accepted_at == datetime.fromisoformat(manifest[KEY]["accepted_at"])
    assert filing.accepted_at_source == "sgml"
    assert filing.issuer_cik == manifest[KEY]["expect"]["issuer_cik"]
    assert session.get(Owner, 999_999_001) is not None


def test_handler_error_rolls_back_and_records(session, settings, tmp_archive, fixture_bytes):
    dispatch.register_handler(["4"], _boom)
    out = ingest_raw(session, fixture_bytes(KEY), settings=settings, archive=tmp_archive, **_raw())
    assert out.status == "error" and out.error == "ValueError: boom"
    filing = session.get(Filing, out.accession_no)
    assert filing is not None
    assert (filing.parse_status, filing.parse_error) == ("error", "ValueError: boom")
    assert session.execute(select(Owner).where(Owner.cik == 999_999_001)).first() is None


def test_unknown_form_skipped(session, settings, tmp_archive, fixture_bytes):
    out = ingest_raw(session, fixture_bytes(KEY), settings=settings, archive=tmp_archive, **_raw())
    assert out.status == "skipped"
    assert session.get(Filing, out.accession_no).parse_status == "skipped"


def test_ingest_accession_duplicate_makes_no_request(session, settings, tmp_archive, manifest):
    acc = manifest[KEY]["accession"]
    make_filing(session, accession_no=acc, parse_status="parsed")
    router = MockRouter({})
    client = SecClient(settings, http=router.client, sleep=lambda s: None)
    out = ingest_accession(
        client, session, cik=manifest[KEY]["cik"], accession=acc, source="feed",
        settings=settings, archive=tmp_archive,
    )
    assert out.status == "duplicate" and router.requests == []


def test_ingest_accession_fetches_and_archives(session, settings, tmp_archive, fixture_bytes, manifest):
    dispatch.register_handler(["4"], _add_owner)
    acc, cik = manifest[KEY]["accession"], manifest[KEY]["cik"]
    router = MockRouter({filing_txt_url(cik, acc): fixture_bytes(KEY)})
    client = SecClient(settings, http=router.client, sleep=lambda s: None)
    first_seen = datetime.fromisoformat("2025-03-31T09:19:30-04:00")
    out = ingest_accession(
        client, session, cik=cik, accession=acc, source="feed", first_seen_at=first_seen,
        settings=settings, archive=tmp_archive,
    )
    assert out.status == "parsed" and len(router.requests) == 1
    assert tmp_archive.exists("filing", acc)
    filing = session.get(Filing, acc)
    assert filing.raw_path and filing.source == "feed" and filing.first_seen_at == first_seen


def test_reparse_uses_archive(session, settings, tmp_archive, fixture_bytes, manifest):
    acc = manifest[KEY]["accession"]
    path = tmp_archive.put("filing", acc, fixture_bytes(KEY))
    dispatch.register_handler(["4"], _boom)
    first = ingest_raw(session, fixture_bytes(KEY), settings=settings, archive=tmp_archive,
                       source="feed", raw_path=str(path), first_seen_at=None)
    assert first.status == "error"
    dispatch.reset_registry()
    dispatch.register_handler(["4"], _add_owner)
    again = reparse_accession(session, acc, settings=settings, archive=tmp_archive)
    assert again.status == "parsed" and session.get(Filing, acc).parse_error is None
