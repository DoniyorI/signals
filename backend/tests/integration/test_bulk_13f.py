import zipfile
from datetime import date, datetime
from io import BytesIO

import pytest
from sqlalchemy import event, func, select, text

from signals.db.models import (
    FeedItem,
    Filing,
    FilingAcceptance,
    FundFiling,
    FundManager,
    FundPosition,
)
from signals.domain.calendars import ET
from signals.ingest.bulk_13f import load_13f_zip
from signals.ingest.normalize_funds import NOTICE_SUMMARY, fund_summary, is_notice


def _seed_filing_acceptance(session, accession_no: str) -> None:
    session.add(
        FilingAcceptance(
            accession_no=accession_no, accepted_at=datetime(2026, 8, 13, 16, 5, tzinfo=ET)
        )
    )
    session.flush()


def test_list_both_naming_styles(fixture_bytes, manifest):
    from signals.ingest.bulk_13f import list_13f_datasets

    html = fixture_bytes("listing_13f_html").decode("utf-8")
    links = list_13f_datasets(html)
    assert len(links) == manifest["listing_13f_html"]["expect"]["n_links"]
    by_name = {link.name: link for link in links}

    quarterly = by_name["2013q2_form13f.zip"]
    assert quarterly.start == date(2013, 4, 1) and quarterly.end == date(2013, 6, 30)

    ranged = by_name["01jun2026-31aug2026_form13f.zip"]
    assert ranged.start == date(2026, 6, 1) and ranged.end == date(2026, 8, 31)
    assert (
        ranged.url
        == "https://www.sec.gov/files/datastandardsinnovation/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip"
    )

    # Sorted ascending by start: the oldest quarterly set comes first.
    assert links[0].name == "2013q2_form13f.zip"


def _values_for(zip_bytes: bytes, accession: str, cusip: str) -> list[float]:
    """Independently read INFOTABLE.tsv straight from the zip (not through the loader)."""
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        raw = zf.read("INFOTABLE.tsv").decode("utf-8")
    lines = [line for line in raw.splitlines() if line]
    header = lines[0].split("\t")
    acc_i, cusip_i, value_i = (
        header.index("ACCESSION_NUMBER"),
        header.index("CUSIP"),
        header.index("VALUE"),
    )
    return [
        float(cells[value_i])
        for line in lines[1:]
        if (cells := line.split("\t"))[acc_i] == accession
        and cells[cusip_i].strip().upper() == cusip
    ]


def test_load_2022_slice_scales_thousands(session, manifest, fixture_bytes):
    zip_bytes = fixture_bytes("bulk_13f_slice_2022")
    load_13f_zip(session, zip_bytes)
    sample = manifest["bulk_13f_slice_2022"]["expect"]["sample"]
    values = _values_for(zip_bytes, sample["accession"], sample["cusip"])
    assert sample["value_reported"] in values  # the anchor row is among the rows summed
    v = session.scalar(
        select(FundPosition.value_usd).where(
            FundPosition.accession_no == sample["accession"],
            FundPosition.cusip == sample["cusip"],
        )
    )
    assert v == pytest.approx(1000 * sum(values))


def test_load_2025_slice_dollars(session, manifest, fixture_bytes):
    zip_bytes = fixture_bytes("bulk_13f_slice_2025")
    load_13f_zip(session, zip_bytes)
    sample = manifest["bulk_13f_slice_2025"]["expect"]["sample"]
    v = session.scalar(
        select(FundPosition.value_usd).where(
            FundPosition.accession_no == sample["accession"],
            FundPosition.cusip == sample["cusip"],
        )
    )
    assert v == pytest.approx(sample["value_reported"])


def test_overlap_dedupes_by_accession(session, manifest, fixture_bytes):
    zip_bytes = fixture_bytes("bulk_13f_slice_2025")
    n_accessions = len(manifest["bulk_13f_slice_2025"]["expect"]["accessions"])

    first = load_13f_zip(session, zip_bytes)
    assert (first.accessions, first.skipped_existing) == (n_accessions, 0)
    before = session.scalar(select(func.count()).select_from(FundPosition))

    second = load_13f_zip(session, zip_bytes)
    assert (second.accessions, second.skipped_existing) == (0, n_accessions)
    after = session.scalar(select(func.count()).select_from(FundPosition))
    assert after == before


def test_restatement_in_slice_marks_superseded(session, manifest, fixture_bytes):
    exp = manifest["bulk_13f_slice_2025"]["expect"]
    load_13f_zip(session, fixture_bytes("bulk_13f_slice_2025"))

    restated = session.get(FundFiling, exp["restatement_accession"])
    assert restated is not None and restated.superseded is False
    restated_positions = session.scalars(
        select(FundPosition).where(FundPosition.accession_no == restated.accession_no)
    ).all()
    assert restated_positions and all(p.is_effective for p in restated_positions)

    original_acc = exp["restatement_original_accession"]
    if session.get(FundFiling, original_acc) is not None:
        original = session.get(FundFiling, original_acc)
        assert original.superseded is True
        original_positions = session.scalars(
            select(FundPosition).where(FundPosition.accession_no == original_acc)
        ).all()
        assert original_positions and not any(p.is_effective for p in original_positions)


def test_new_holdings_without_a_sibling_base_is_not_effective(session, manifest, fixture_bytes):
    # This slice has no other filing for this (filer, period): the plan's rule from B2 (a NEW
    # HOLDINGS amendment needs a base to be effective) applies exactly the same via the bulk path.
    exp = manifest["bulk_13f_slice_2025"]["expect"]
    load_13f_zip(session, fixture_bytes("bulk_13f_slice_2025"))
    positions = session.scalars(
        select(FundPosition).where(FundPosition.accession_no == exp["new_holdings_accession"])
    ).all()
    assert positions and not any(p.is_effective for p in positions)


def test_notice_has_no_positions_and_the_notice_summary(session, manifest, fixture_bytes):
    exp = manifest["bulk_13f_slice_2025"]["expect"]
    load_13f_zip(session, fixture_bytes("bulk_13f_slice_2025"))
    notice_acc = exp["notice_accession"]
    assert (
        session.scalar(
            select(func.count())
            .select_from(FundPosition)
            .where(FundPosition.accession_no == notice_acc)
        )
        == 0
    )
    item = session.get(FeedItem, notice_acc)
    assert item is not None
    assert item.summary == "13F notice (holdings reported by another manager)"
    filing = session.get(Filing, notice_acc)
    assert filing is not None and filing.parse_status == "parsed" and filing.source == "bulk_13f"


def test_old_period_loads_into_the_default_partition(session, manifest, fixture_bytes):
    # spec/plan real-data note: one filing in this slice reports period 2001-09-30.
    exp = manifest["bulk_13f_slice_2025"]["expect"]
    load_13f_zip(session, fixture_bytes("bulk_13f_slice_2025"))
    filing = session.get(Filing, exp["old_period_accession"])
    assert filing is not None and filing.period_of_report == date(2001, 9, 30)
    n = session.scalar(
        select(func.count())
        .select_from(FundPosition)
        .where(FundPosition.accession_no == exp["old_period_accession"])
    )
    assert n > 0


def test_feed_item_summary_for_a_regular_filing(session, manifest, fixture_bytes):
    load_13f_zip(session, fixture_bytes("bulk_13f_slice_2025"))
    sample_acc = manifest["bulk_13f_slice_2025"]["expect"]["sample"]["accession"]
    item = session.get(FeedItem, sample_acc)
    n = session.scalar(
        select(func.count())
        .select_from(FundPosition)
        .where(FundPosition.accession_no == sample_acc)
    )
    total = session.scalar(
        select(func.sum(FundPosition.value_usd)).where(FundPosition.accession_no == sample_acc)
    )
    assert item is not None
    assert item.codes == ["13F-HR"] and item.direction == "other"
    assert f"{n} positions" in item.summary and item.summary.startswith("13F for Q")
    assert item.owner_ciks and total is not None


def test_manager_name_and_accepted_at_from_filing_acceptance(session, manifest, fixture_bytes):
    exp = manifest["bulk_13f_slice_2025"]["expect"]
    sample_acc = exp["sample"]["accession"]
    _seed_filing_acceptance(session, sample_acc)
    load_13f_zip(session, fixture_bytes("bulk_13f_slice_2025"))
    filing = session.get(Filing, sample_acc)
    assert filing is not None
    assert filing.accepted_at is not None and filing.accepted_at_source == "submissions"
    other = session.get(Filing, exp["old_period_accession"])
    assert other is not None and other.accepted_at is None and other.accepted_at_source == "missing"
    manager = session.get(FundManager, 1061768)  # BAUPOST GROUP LLC/MA, from COVERPAGE
    assert manager is not None and manager.name == "BAUPOST GROUP LLC/MA"


def test_bulk_feed_totals_do_not_rescan_historical_positions(session, fixture_bytes):
    """The feed must reuse this batch's normalized totals, not scan history per filing."""
    queries = []
    connection = session.connection()

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().startswith("SELECT") and "AS n_positions" in statement:
            queries.append(statement)

    event.listen(connection, "before_cursor_execute", capture)
    try:
        load_13f_zip(session, fixture_bytes("bulk_13f_slice_2025"))
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert len(queries) == 1
    explained = session.scalar(text("EXPLAIN (ANALYZE, FORMAT JSON) " + queries[0]))

    def historical_scans(node):
        scans = int(node.get("Relation Name", "").startswith("fund_positions"))
        return scans + sum(historical_scans(child) for child in node.get("Plans", []))

    assert historical_scans(explained[0]["Plan"]) == 0


@pytest.mark.parametrize("fixture", ["bulk_13f_slice_2022", "bulk_13f_slice_2025"])
def test_bulk_feed_matches_legacy_position_totals(session, fixture_bytes, fixture):
    load_13f_zip(session, fixture_bytes(fixture))
    legacy = session.execute(
        text("""
            SELECT ff.accession_no, ff.submission_type, ff.period_of_report,
                   count(p.accession_no) AS n_positions,
                   coalesce(sum(p.value_usd), 0) AS total_value
            FROM fund_filings ff
            LEFT JOIN fund_positions p ON p.accession_no = ff.accession_no
            GROUP BY ff.accession_no, ff.submission_type, ff.period_of_report
        """)
    ).all()
    before = {}
    for row in legacy:
        item = session.get(FeedItem, row.accession_no)
        assert item is not None
        expected = (
            NOTICE_SUMMARY
            if is_notice(row.submission_type)
            else fund_summary(row.period_of_report, row.n_positions, row.total_value)
        )
        assert item.summary == expected
        before[row.accession_no] = (item.summary, item.form_type, item.codes, item.owner_ciks)
    load_13f_zip(session, fixture_bytes(fixture))
    for accession, expected_item in before.items():
        item = session.get(FeedItem, accession)
        assert item is not None
        assert (item.summary, item.form_type, item.codes, item.owner_ciks) == expected_item
