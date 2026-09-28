from datetime import date, datetime

import pytest
from sqlalchemy import select

from signals.db.models import Filing, InsiderHolding, InsiderTransaction
from signals.domain.calendars import ET
from signals.ingest import dispatch
from signals.ingest.amendments import link_amendment, relink_orphans
from tests.factories import make_filing, make_holding, make_transaction
from tests.integration.insider_support import make_loader, register_ownership_handler


@pytest.fixture(autouse=True)
def ownership_handler():
    register_ownership_handler()
    yield
    dispatch.reset_registry()


@pytest.fixture
def load(fixture_bytes, settings, tmp_archive):
    return make_loader(fixture_bytes, settings, tmp_archive)


def _superseded(session, acc: str) -> list[str | None]:
    return list(
        session.scalars(
            select(InsiderTransaction.superseded_by)
            .where(InsiderTransaction.accession_no == acc)
            .order_by(InsiderTransaction.table_kind, InsiderTransaction.row_no)
        )
    )


def _flags(session, acc: str) -> list[list[str]]:
    return list(
        session.scalars(
            select(InsiderTransaction.flags).where(InsiderTransaction.accession_no == acc)
        )
    )


def test_amendment_supersedes_original(session, load, manifest):
    original = load(session, "form4a_original")
    amendment = load(session, "form4a_amendment")
    assert original == manifest["form4a_original"]["accession"]
    assert set(_superseded(session, original)) == {amendment}
    assert len(_superseded(session, original)) == 5
    assert set(_superseded(session, amendment)) == {None}
    filing = session.get(Filing, amendment)
    assert filing.amends_accession == original
    assert filing.original_filed_date == date(2025, 3, 28)
    assert all("orphan_amendment" not in f for f in _flags(session, amendment))


def test_orphan_then_relinked(session, load):
    amendment = load(session, "form4a_amendment")
    assert all("orphan_amendment" in f for f in _flags(session, amendment))
    assert len(_flags(session, amendment)) == 6
    assert session.get(Filing, amendment).amends_accession is None
    original = load(session, "form4a_original")
    assert relink_orphans(session) == 1
    assert all("orphan_amendment" not in f for f in _flags(session, amendment))
    assert set(_superseded(session, original)) == {amendment}
    assert session.get(Filing, amendment).amends_accession == original
    assert relink_orphans(session) == 0


def test_reparsed_original_stays_superseded(session, load):
    original = load(session, "form4a_original")
    amendment = load(session, "form4a_amendment")
    load(session, "form4a_original", force=True)
    assert set(_superseded(session, original)) == {amendment}


def _amendment(
    session, accession: str, *, filed: date, original_date: date | None, owners=(2000001,)
):
    filing = make_filing(
        session, accession_no=accession, form_type="4/A", filed_date=filed, owners=owners
    )
    filing.original_filed_date = original_date
    session.flush()
    return filing


def test_multiple_candidates_pick_overlap(session):
    first = make_filing(session, accession_no="0002000001-24-000001", filed_date=date(2024, 1, 16))
    second = make_filing(session, accession_no="0002000001-24-000002", filed_date=date(2024, 1, 16))
    make_transaction(session, accession_no=first.accession_no, transaction_date=date(2024, 1, 10))
    make_transaction(session, accession_no=second.accession_no, transaction_date=date(2024, 1, 11))
    amendment = _amendment(
        session, "0002000001-24-000003", filed=date(2024, 1, 20), original_date=date(2024, 1, 16)
    )
    make_transaction(
        session, accession_no=amendment.accession_no, transaction_date=date(2024, 1, 11)
    )
    assert link_amendment(session, amendment.accession_no) == second.accession_no
    assert _superseded(session, second.accession_no) == [amendment.accession_no]
    assert _superseded(session, first.accession_no) == [None]


def test_equal_overlap_prefers_latest_accepted(session):
    early = make_filing(
        session,
        accession_no="0002000001-24-000001",
        accepted_at=datetime(2024, 1, 16, 16, 30, tzinfo=ET),
    )
    late = make_filing(
        session,
        accession_no="0002000001-24-000002",
        accepted_at=datetime(2024, 1, 16, 18, 5, tzinfo=ET),
    )
    for f in (early, late):
        make_transaction(session, accession_no=f.accession_no, transaction_date=date(2024, 1, 11))
    amendment = _amendment(
        session, "0002000001-24-000003", filed=date(2024, 1, 20), original_date=date(2024, 1, 16)
    )
    make_transaction(
        session, accession_no=amendment.accession_no, transaction_date=date(2024, 1, 11)
    )
    assert link_amendment(session, amendment.accession_no) == late.accession_no


def test_candidate_needs_common_owner_same_issuer_and_date(session):
    other_owner = make_filing(session, accession_no="0002000009-24-000001", owners=(2000009,))
    other_issuer = make_filing(session, accession_no="0002000001-24-000004", issuer_cik=1000002)
    other_day = make_filing(
        session, accession_no="0002000001-24-000005", filed_date=date(2024, 1, 17)
    )
    for f in (other_owner, other_issuer, other_day):
        make_transaction(session, accession_no=f.accession_no, issuer_cik=f.issuer_cik or 0)
    amendment = _amendment(
        session, "0002000001-24-000006", filed=date(2024, 1, 20), original_date=date(2024, 1, 16)
    )
    make_transaction(session, accession_no=amendment.accession_no)
    assert link_amendment(session, amendment.accession_no) is None
    assert _flags(session, amendment.accession_no) == [["orphan_amendment"]]
    for f in (other_owner, other_issuer, other_day):
        assert _superseded(session, f.accession_no) == [None]


def test_unknown_original_date_is_orphan(session):
    make_filing(session, accession_no="0002000001-24-000001")
    amendment = _amendment(
        session, "0002000001-24-000002", filed=date(2024, 1, 20), original_date=None
    )
    make_transaction(session, accession_no=amendment.accession_no)
    assert link_amendment(session, amendment.accession_no) is None
    assert link_amendment(session, amendment.accession_no) is None
    assert _flags(session, amendment.accession_no) == [["orphan_amendment"]]


def test_later_amendment_supersedes_original_and_earlier_amendment(session):
    original = make_filing(session, accession_no="0002000001-24-000001")
    make_transaction(session, accession_no=original.accession_no)
    make_holding(session, accession_no=original.accession_no)
    first = _amendment(
        session, "0002000001-24-000002", filed=date(2024, 1, 20), original_date=date(2024, 1, 16)
    )
    second = _amendment(
        session, "0002000001-24-000003", filed=date(2024, 1, 25), original_date=date(2024, 1, 16)
    )
    for f in (first, second):
        make_transaction(session, accession_no=f.accession_no)
    assert link_amendment(session, first.accession_no) == original.accession_no
    assert _superseded(session, original.accession_no) == [first.accession_no]
    assert link_amendment(session, second.accession_no) == original.accession_no
    assert link_amendment(session, first.accession_no) == original.accession_no  # re-entrant
    assert _superseded(session, original.accession_no) == [second.accession_no]
    assert _superseded(session, first.accession_no) == [second.accession_no]
    assert _superseded(session, second.accession_no) == [None]
    holding = session.scalars(
        select(InsiderHolding.superseded_by).where(
            InsiderHolding.accession_no == original.accession_no
        )
    ).one()
    assert holding == second.accession_no
