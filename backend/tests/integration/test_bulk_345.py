from datetime import UTC, datetime

from sqlalchemy import event, select

from signals.db.models import FeedItem, Filing, FilingAcceptance, InsiderHolding, InsiderTransaction
from signals.domain.owner_group import owner_group_key
from signals.ingest.bulk_345 import apply_acceptance_times, list_345_datasets, load_345_zip
from tests.factories import make_filing


def test_list_datasets(fixture_bytes, manifest):
    html = fixture_bytes("listing_345_html").decode("utf-8")
    links = list_345_datasets(html)
    exp = manifest["listing_345_html"]["expect"]
    assert len(links) == exp["n_links"]
    assert links[0].name == exp["first"]
    assert links[-1].name == exp["last"]
    for link in links:
        assert link.url.startswith("https://www.sec.gov/")
    assert links == sorted(links, key=lambda link: (link.year, link.quarter))


def test_load_slice_counts(session, fixture_bytes, manifest):
    exp = manifest["bulk_345_slice"]["expect"]
    result = load_345_zip(session, fixture_bytes("bulk_345_slice"))
    assert result.accessions == len(exp["accessions"])
    assert result.skipped_existing == 0
    assert result.transactions == exp["n_nonderiv_trans"] + exp["n_deriv_trans"]
    assert result.holdings == exp["n_nonderiv_holding"] + exp["n_deriv_holding"]

    stored = set(session.scalars(select(Filing.accession_no)).all())
    assert stored == set(exp["accessions"])
    assert all(f.parse_status == "parsed" and f.source == "bulk_345" for f in session.query(Filing))


def test_owner_group_matches_python(session, fixture_bytes, manifest):
    exp = manifest["bulk_345_slice"]["expect"]
    load_345_zip(session, fixture_bytes("bulk_345_slice"))
    acc = exp["joint_accession"]
    groups = set(
        session.scalars(
            select(InsiderTransaction.owner_group).where(InsiderTransaction.accession_no == acc)
        )
    )
    # Recompute independently from filing_owners rather than trusting owner_group itself.
    from signals.db.models import FilingOwner

    ciks = session.scalars(
        select(FilingOwner.owner_cik).where(FilingOwner.accession_no == acc)
    ).all()
    assert len(ciks) > 1  # this fixture's accession is a joint filing
    assert groups == {owner_group_key(ciks)}


def test_plan_flag_footnote_in_bulk(session, fixture_bytes, manifest):
    exp = manifest["bulk_345_slice"]["expect"]
    load_345_zip(session, fixture_bytes("bulk_345_slice"))

    footnote_acc = exp["footnote_10b5_1_accession"]
    flags = set(
        session.scalars(
            select(InsiderTransaction.plan_10b5_1).where(
                InsiderTransaction.accession_no == footnote_acc
            )
        )
    )
    assert "footnote" in flags

    flag_acc = exp["flag_10b5_1_accession"]
    flags2 = set(
        session.scalars(
            select(InsiderTransaction.plan_10b5_1).where(
                InsiderTransaction.accession_no == flag_acc
            )
        )
    )
    assert flags2 == {"flag"}


def test_skips_accessions_already_parsed(session, fixture_bytes, manifest):
    exp = manifest["bulk_345_slice"]["expect"]
    pre_seeded = exp["accessions"][0]
    make_filing(session, accession_no=pre_seeded, form_type="4", parse_status="parsed")
    session.flush()

    result = load_345_zip(session, fixture_bytes("bulk_345_slice"))
    assert result.skipped_existing == 1
    assert result.accessions == len(exp["accessions"]) - 1

    # The pre-seeded filing's own rows (from the factory, not the bulk file) are untouched.
    assert session.get(Filing, pre_seeded).source == "feed"
    tx_count = session.scalar(
        select(InsiderTransaction).where(InsiderTransaction.accession_no == pre_seeded)
    )
    assert tx_count is None  # factory made no transaction rows for it


def test_idempotent(session, fixture_bytes, manifest):
    exp = manifest["bulk_345_slice"]["expect"]
    load_345_zip(session, fixture_bytes("bulk_345_slice"))
    session.flush()
    tx_count_1 = len(session.scalars(select(InsiderTransaction.id)).all())
    holding_count_1 = len(session.scalars(select(InsiderHolding.id)).all())

    # A second load over the same (uncommitted) zip must see every accession as already
    # parse_status='parsed' and skip all of them, rather than duplicating any row.
    result2 = load_345_zip(session, fixture_bytes("bulk_345_slice"))
    session.flush()
    tx_count_2 = len(session.scalars(select(InsiderTransaction.id)).all())
    holding_count_2 = len(session.scalars(select(InsiderHolding.id)).all())

    assert result2.accessions == 0
    assert result2.skipped_existing == len(exp["accessions"])
    assert tx_count_2 == tx_count_1
    assert holding_count_2 == holding_count_1


def test_apply_acceptance_times(session, fixture_bytes, manifest):
    exp = manifest["bulk_345_slice"]["expect"]
    load_345_zip(session, fixture_bytes("bulk_345_slice"))
    acc = exp["accessions"][0]
    assert session.get(Filing, acc).accepted_at is None

    accepted = datetime(2025, 3, 31, 16, 30, tzinfo=UTC)
    session.add(
        FilingAcceptance(
            accession_no=acc, cik=None, form_type="4", filing_date=None, accepted_at=accepted
        )
    )
    session.flush()

    updated = apply_acceptance_times(session)
    assert updated >= 1
    session.expire_all()
    filing = session.get(Filing, acc)
    assert filing.accepted_at == accepted
    assert filing.accepted_at_source == "submissions"
    feed_item = session.get(FeedItem, acc)
    assert feed_item.accepted_at == accepted


def test_bulk_ticker_evidence_locks_follow_canonical_key_order(session, fixture_bytes):
    keys = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO ticker_evidence"):
            keys.append((parameters["issuer_cik"], parameters["symbol"]))

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", observe)
    try:
        load_345_zip(session, fixture_bytes("bulk_345_slice"))
    finally:
        event.remove(connection, "before_cursor_execute", observe)
    assert len(set(keys)) > 1
    assert keys == sorted(keys)
