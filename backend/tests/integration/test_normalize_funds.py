from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from signals.db.models import FeedItem, FundFiling, FundManager, FundPosition
from signals.domain.calendars import ET
from signals.domain.types import FUND_FORMS
from signals.ingest import dispatch
from signals.ingest.normalize_funds import (
    NOTICE_SUMMARY,
    fund_summary,
    normalize_13f,
    refresh_effective,
)
from signals.ingest.parsers.form13f import F13FCover, parse_13f_infotable, parse_13f_primary
from signals.ingest.pipeline import ingest_raw
from signals.sec.sgml import SgmlFiling
from tests.factories import make_filing, make_fund_filing, make_fund_manager, make_fund_position


def _handle(session, sgml: SgmlFiling, filing, ctx) -> None:
    """A local stand-in for the B8 handler: primary document plus information table."""
    cover, rows = None, []
    for doc in sgml.xml_documents():
        body = doc.xml()
        assert body is not None
        if doc.type == "INFORMATION TABLE":
            rows = parse_13f_infotable(body)
        elif doc.type == sgml.form_type:
            cover = parse_13f_primary(body)
    assert cover is not None
    normalize_13f(session, filing, cover, rows)


@pytest.fixture(autouse=True)
def local_handler():
    dispatch.reset_registry()
    dispatch.register_handler(FUND_FORMS, _handle)
    yield
    dispatch.reset_registry()


@pytest.fixture
def load(session, settings, tmp_archive, fixture_bytes):
    def _load(key: str) -> str:
        out = ingest_raw(
            session,
            fixture_bytes(key),
            source="test",
            raw_path=None,
            first_seen_at=None,
            settings=settings,
            archive=tmp_archive,
        )
        assert out.status == "parsed", out.error
        return out.accession_no

    return _load


def _parsed_rows(fixture_bytes, key: str):
    sg = SgmlFiling.from_txt(fixture_bytes(key))
    body = next(d for d in sg.xml_documents() if d.type == "INFORMATION TABLE").xml()
    assert body is not None
    return parse_13f_infotable(body)


def _positions(session, acc: str) -> list[FundPosition]:
    return list(session.scalars(select(FundPosition).where(FundPosition.accession_no == acc)))


def test_small_13f_positions(session, manifest, load):
    acc = load("f13f_small")
    n = session.scalar(
        select(func.count()).select_from(FundPosition).where(FundPosition.accession_no == acc)
    )
    assert 0 < n <= manifest["f13f_small"]["expect"]["n_rows"]
    ff = session.get(FundFiling, acc)
    assert ff is not None and (ff.filer_cik, ff.period_of_report) == (1061165, date(2026, 6, 30))
    assert ff.value_total_usd == manifest["f13f_small"]["expect"]["table_value_total"]
    assert ff.accepted_at == datetime.fromisoformat(manifest["f13f_small"]["accepted_at"])
    assert (ff.submission_type, ff.superseded, ff.entry_total) == ("13F-HR", False, 34)
    assert all(p.is_effective and p.filer_cik == 1061165 for p in _positions(session, acc))
    assert session.get(FundManager, 1061165).name == "LONE PINE CAPITAL LLC"


def test_pre2023_values_scaled(session, manifest, load, fixture_bytes):
    acc = load("f13f_pre2023")
    first = manifest["f13f_pre2023"]["expect"]["first_row"]
    v = session.scalar(
        select(func.sum(FundPosition.value_usd)).where(
            FundPosition.accession_no == acc, FundPosition.cusip == first["cusip"]
        )
    )
    assert v >= first["value_reported"] * 1000
    # Berkshire reports this CUSIP on 3 rows (one per other-manager combination).
    rows = _parsed_rows(fixture_bytes, "f13f_pre2023")
    same = [r.value_reported for r in rows if r.cusip == first["cusip"]]
    assert len(same) == 3 and v == pytest.approx(sum(same) * 1000)


def test_duplicate_rows_aggregate_per_cusip(session, manifest, load, fixture_bytes):
    acc = load("f13f_pre2023")
    rows = _parsed_rows(fixture_bytes, "f13f_pre2023")
    positions = _positions(session, acc)
    assert len(positions) == len({(r.cusip, r.put_call or "") for r in rows}) < len(rows)
    total = sum(p.value_usd or 0 for p in positions)
    assert total == pytest.approx(manifest["f13f_pre2023"]["expect"]["table_value_total"] * 1000)
    apple = next(p for p in positions if p.cusip == "037833100")
    apple_rows = [r for r in rows if r.cusip == "037833100"]
    assert apple.shares == sum(r.shares for r in apple_rows)
    assert (apple.name_of_issuer, apple.title_of_class, apple.put_call, apple.sh_prn) == (
        apple_rows[0].name_of_issuer,
        apple_rows[0].title_of_class,
        "",
        "SH",
    )


def test_feed_item_for_13f(session, load):
    acc = load("f13f_pre2023")
    item = session.get(FeedItem, acc)
    n = len(_positions(session, acc))
    assert item is not None and item.summary == f"13F for Q3 2022: {n} positions, $296.1B"
    assert (item.direction, item.codes, item.owner_ciks) == ("other", ["13F-HR"], [1067983])
    assert item.owner_names == "Berkshire Hathaway Inc" and item.form_type == "13F-HR"
    assert item.filed_date == date(2022, 11, 14) and item.accepted_at is not None


def test_reparse_replaces_positions(session, load):
    acc = load("f13f_small")
    before = len(_positions(session, acc))
    load("f13f_small")
    assert len(_positions(session, acc)) == before


def test_restatement_fixture_supersedes_original(session, load):
    original = make_fund_filing(
        session,
        accession_no="0002098824-26-000003",
        filer_cik=2098824,
        period=date(2026, 6, 30),
        filed_date=date(2026, 8, 7),
    )
    make_fund_position(
        session, accession_no=original.accession_no, filer_cik=2098824, period=date(2026, 6, 30)
    )
    acc = load("f13f_restatement")
    session.refresh(original)
    assert original.superseded is True and session.get(FundFiling, acc).superseded is False
    old = _positions(session, original.accession_no)
    assert old and not any(p.is_effective for p in old)
    assert all(p.is_effective for p in _positions(session, acc))


def test_restatement_and_new_holdings(session):
    make_fund_manager(session)
    orig = make_fund_filing(
        session, accession_no="0003000001-24-000001", filed_date=date(2024, 5, 15)
    )
    make_fund_position(session, accession_no=orig.accession_no, cusip="000000AA1")
    rest = make_fund_filing(
        session,
        accession_no="0003000001-24-000002",
        filed_date=date(2024, 6, 1),
        submission_type="13F-HR/A",
        amendment_type="RESTATEMENT",
    )
    make_fund_position(session, accession_no=rest.accession_no, cusip="000000BB2")
    add = make_fund_filing(
        session,
        accession_no="0003000001-24-000003",
        filed_date=date(2024, 6, 10),
        submission_type="13F-HR/A",
        amendment_type="NEW HOLDINGS",
    )
    make_fund_position(session, accession_no=add.accession_no, cusip="000000CC3")
    refresh_effective(session, 3000001, date(2024, 3, 31))
    eff = set(session.scalars(select(FundPosition.cusip).where(FundPosition.is_effective)))
    assert eff == {"000000BB2", "000000CC3"}
    flags = dict(session.execute(select(FundFiling.accession_no, FundFiling.superseded)).all())
    assert flags == {orig.accession_no: True, rest.accession_no: False, add.accession_no: False}


def test_new_holdings_before_a_restatement_is_replaced(session):
    add = make_fund_filing(
        session,
        accession_no="0003000001-24-000002",
        filed_date=date(2024, 5, 20),
        submission_type="13F-HR/A",
        amendment_type="NEW HOLDINGS",
    )
    orig = make_fund_filing(
        session, accession_no="0003000001-24-000001", filed_date=date(2024, 5, 15)
    )
    rest = make_fund_filing(
        session,
        accession_no="0003000001-24-000003",
        filed_date=date(2024, 6, 1),
        submission_type="13F-HR/A",
        amendment_type="RESTATEMENT",
    )
    for f, cusip in [(orig, "000000AA1"), (add, "000000BB2"), (rest, "000000CC3")]:
        make_fund_position(session, accession_no=f.accession_no, cusip=cusip)
    refresh_effective(session, 3000001, date(2024, 3, 31))
    eff = set(session.scalars(select(FundPosition.cusip).where(FundPosition.is_effective)))
    assert eff == {"000000CC3"}


def test_restatement_wins_when_original_lacks_acceptance_time(session):
    # A bulk-loaded original can lack an acceptance time while its XML-parsed amendment has one.
    orig = make_fund_filing(
        session, accession_no="0003000001-24-000001", filed_date=date(2024, 5, 15)
    )
    rest = make_fund_filing(
        session,
        accession_no="0003000001-24-000002",
        filed_date=date(2024, 6, 1),
        accepted_at=datetime(2024, 6, 1, 10, 0, tzinfo=ET),
        submission_type="13F-HR/A",
        amendment_type="RESTATEMENT",
    )
    make_fund_position(session, accession_no=orig.accession_no, cusip="000000AA1")
    make_fund_position(session, accession_no=rest.accession_no, cusip="000000BB2")
    refresh_effective(session, 3000001, date(2024, 3, 31))
    eff = set(session.scalars(select(FundPosition.cusip).where(FundPosition.is_effective)))
    assert eff == {"000000BB2"}


def test_new_holdings_without_a_base_is_not_effective(session):
    add = make_fund_filing(session, submission_type="13F-HR/A", amendment_type="NEW HOLDINGS")
    make_fund_position(session, accession_no=add.accession_no)
    refresh_effective(session, 3000001, date(2024, 3, 31))
    session.refresh(add)
    assert add.superseded is True
    assert session.scalar(select(func.count()).where(FundPosition.is_effective)) == 0


def test_notice_writes_filing_without_positions(session):
    filing = make_filing(
        session,
        accession_no="0000921895-26-001911",
        form_type="13F-NT",
        issuer_cik=None,
        primary_cik=1016268,
        filed_date=date(2026, 7, 31),
        owners=(),
    )
    cover = F13FCover(
        submission_type="13F-NT",
        period_of_report=date(2026, 6, 30),
        is_amendment=False,
        amendment_no=None,
        amendment_type=None,
        report_type="13F NOTICE",
        manager_name="BRAMSON EDWARD J",
        other_included_managers=None,
        table_entry_total=None,
        table_value_total=None,
        is_confidential_omitted=None,
    )
    normalize_13f(session, filing, cover, [])
    ff = session.get(FundFiling, filing.accession_no)
    assert ff is not None and ff.submission_type == "13F-NT" and ff.value_total_usd is None
    assert _positions(session, filing.accession_no) == []
    item = session.get(FeedItem, filing.accession_no)
    assert item is not None and item.summary == NOTICE_SUMMARY and item.codes == ["13F-NT"]
    assert session.get(FundManager, 1016268).name == "BRAMSON EDWARD J"


def test_manager_name_follows_the_newest_filing(session, load):
    newer = make_fund_filing(
        session,
        accession_no="0000919574-26-009999",
        filer_cik=1061165,
        period=date(2026, 9, 30),
        filed_date=date(2026, 11, 14),
    )
    make_fund_manager(session, cik=1061165, name="LONE PINE CAPITAL LLC (RENAMED)")
    load("f13f_small")  # filed 2026-08-14, older than `newer`
    assert session.get(FundManager, newer.filer_cik).name == "LONE PINE CAPITAL LLC (RENAMED)"


def test_fund_summary():
    assert (
        fund_summary(date(2026, 6, 30), 45, 268_100_000_000)
        == "13F for Q2 2026: 45 positions, $268.1B"
    )
    assert fund_summary(date(2024, 3, 31), 3, 950) == "13F for Q1 2024: 3 positions, $950"
    assert fund_summary(date(2024, 12, 31), 7, 12_345_678) == "13F for Q4 2024: 7 positions, $12.3M"
    assert fund_summary(date(2024, 9, 30), 2, 45_600) == "13F for Q3 2024: 2 positions, $46K"
