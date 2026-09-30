from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from signals.db.models import FeedItem, OwnershipStake
from signals.domain.calendars import ET
from signals.domain.types import STAKE_FORMS
from signals.ingest import dispatch
from signals.ingest.normalize_stakes import normalize_stake
from signals.ingest.parsers.schedule13 import ReportingPerson, Schedule13Doc, parse_schedule13
from signals.ingest.pipeline import ingest_raw
from signals.sec.sgml import SgmlFiling
from tests.factories import make_filing


def _handle(session, sgml: SgmlFiling, filing, ctx) -> None:
    """A local stand-in for the B8 handler: the first XML document holds the whole filing."""
    doc_ = next(d for d in sgml.xml_documents() if d.type == sgml.form_type)
    body = doc_.xml()
    assert body is not None
    doc = parse_schedule13(body, sgml.form_type)
    normalize_stake(session, filing, doc)


@pytest.fixture(autouse=True)
def local_handler():
    dispatch.reset_registry()
    dispatch.register_handler(STAKE_FORMS, _handle)
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


def test_sc13d_stake_fields(session, load):
    acc = load("sc13d")
    stake = session.get(OwnershipStake, acc)
    assert stake is not None
    assert stake.is_activist is True
    assert (stake.issuer_cik, stake.cusip) == (2088082, "284825106")
    assert stake.percent_of_class == pytest.approx(0.11)
    assert stake.shares == pytest.approx(6885170.0)
    assert stake.group_key == "1055951|1760648|1808744"
    assert len(stake.reporting_persons) == 3
    assert stake.is_current is True
    assert stake.purpose_excerpt is not None
    assert stake.purpose_excerpt.startswith("This Statement on Schedule 13D relates")


def test_sc13g_stake_fields(session, load):
    acc = load("sc13g")
    stake = session.get(OwnershipStake, acc)
    assert stake is not None
    assert stake.is_activist is False
    assert (stake.issuer_cik, stake.cusip) == (1650101, "00653L400")
    assert stake.percent_of_class == pytest.approx(0.099)
    assert stake.shares == pytest.approx(208334.0)
    # The sole person has no CIK in this fixture, so the group falls back to the upper-cased name.
    assert stake.group_key == "YIP WAI LUN"
    assert stake.purpose_excerpt is None  # only 13D carries a purpose
    assert stake.is_current is True


def test_feed_item_for_13d(session, load):
    acc = load("sc13d")
    item = session.get(FeedItem, acc)
    assert item is not None
    assert item.summary == "13D: 11.0% of class"
    assert item.codes == ["SCHEDULE 13D"]
    assert item.issuer_cik == 2088082 and item.direction == "other"
    assert item.owner_ciks == [1055951, 1760648, 1808744]


def test_feed_item_for_13g(session, load):
    acc = load("sc13g")
    item = session.get(FeedItem, acc)
    assert item is not None and item.summary == "13G: 9.9% of class"
    assert item.codes == ["SCHEDULE 13G"]


def test_is_current_flips(session, load):
    old_acc = load("sc13g")
    # A later 13G/A for the same reporting-person group and issuer, percent unknown this round.
    filing = make_filing(
        session,
        accession_no="0001493152-26-999999",
        form_type="SCHEDULE 13G/A",
        issuer_cik=1650101,
        primary_cik=2152205,
        filed_date=date(2026, 10, 1),
        accepted_at=datetime(2026, 10, 1, 8, 0, tzinfo=ET),
        owners=(),
    )
    doc = Schedule13Doc(
        form_type="SCHEDULE 13G/A",
        issuer_cik=1650101,
        issuer_name="ADDENTAX GROUP CORP.",
        cusip="00653L400",
        event_date=date(2026, 9, 30),
        amendment_no=1,
        persons=(
            ReportingPerson(
                name="Yip Wai Lun",
                cik=None,
                sole_voting=None,
                shared_voting=None,
                sole_dispositive=None,
                shared_dispositive=None,
                aggregate_owned=None,
                percent_of_class=None,
                type_of_reporting_person="IN",
            ),
        ),
        purpose=None,
    )
    normalize_stake(session, filing, doc)

    old = session.get(OwnershipStake, old_acc)
    new = session.get(OwnershipStake, filing.accession_no)
    assert old.is_current is False
    assert new.is_current is True
    # Percent is unknown this round, so the summary falls back to a plain "filed" notice.
    assert session.get(FeedItem, filing.accession_no).summary == "13G filed"


def test_reparse_replaces_the_same_row(session, load):
    acc = load("sc13d")
    before = session.get(OwnershipStake, acc).updated_at
    load("sc13d")
    after = session.get(OwnershipStake, acc)
    assert after.updated_at >= before
    assert session.scalar(select(func.count()).select_from(OwnershipStake)) == 1
