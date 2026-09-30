from datetime import date, datetime

from sqlalchemy import func, select

from signals.analytics.decisions import build_decisions
from signals.db.models import Decision, DecisionOwner
from signals.domain.calendars import ET
from tests.factories import make_filing, make_issuer, make_transaction


def _decisions(session) -> list[Decision]:
    return list(session.scalars(select(Decision).order_by(Decision.issuer_cik, Decision.id)))


def test_ignores_superseded_and_non_ps(session):
    make_issuer(session)
    make_filing(session, accession_no="0002000001-24-000001")
    for row, code in enumerate(["A", "M", "F", "G"], start=1):
        make_transaction(session, accession_no="0002000001-24-000001", code=code, row_no=row)
    make_transaction(
        session,
        accession_no="0002000001-24-000001",
        code="P",
        row_no=5,
        superseded_by="0002000001-24-000009",
    )
    make_transaction(
        session, accession_no="0002000001-24-000001", code="P", row_no=6, table_kind="deriv"
    )
    assert build_decisions(session) == 0
    assert _decisions(session) == []


def test_joint_filing_one_decision_two_owners(session):
    make_issuer(session)
    make_filing(session, accession_no="0002000003-24-000001", owners=(2000003, 2000004))
    make_transaction(session, accession_no="0002000003-24-000001", owner_ciks=(2000003, 2000004))
    assert build_decisions(session) == 1
    (d,) = _decisions(session)
    owners = session.scalars(
        select(DecisionOwner.owner_cik).where(DecisionOwner.decision_id == d.id)
    ).all()
    assert d.owner_group == "2000003|2000004" and sorted(owners) == [2000003, 2000004]
    assert (d.direction, d.shares, d.vwap, d.value_usd) == ("buy", 1000.0, 10.0, 10000.0)
    assert d.stake_change_pct == 0.1 and not d.is_new_position and not d.is_planned


def test_accessions_collected(session):
    make_issuer(session)
    make_filing(
        session,
        accession_no="0002000001-24-000002",
        filed_date=date(2024, 1, 19),
        accepted_at=datetime(2024, 1, 19, 16, 30, tzinfo=ET),
    )
    make_filing(
        session,
        accession_no="0002000001-24-000001",
        filed_date=date(2024, 1, 16),
        accepted_at=datetime(2024, 1, 16, 16, 30, tzinfo=ET),
    )
    make_transaction(
        session, accession_no="0002000001-24-000001", transaction_date=date(2024, 1, 12)
    )
    make_transaction(
        session,
        accession_no="0002000001-24-000002",
        transaction_date=date(2024, 1, 17),
        shares_owned_after=12000.0,
    )
    assert build_decisions(session) == 1
    (d,) = _decisions(session)
    assert d.accessions == ["0002000001-24-000001", "0002000001-24-000002"]
    assert d.first_accession == "0002000001-24-000001"
    assert d.accepted_at == datetime(2024, 1, 16, 16, 30, tzinfo=ET)
    assert (d.first_trade_date, d.last_trade_date) == (date(2024, 1, 12), date(2024, 1, 17))
    assert d.lag_days == 1 and d.shares == 2000.0  # Jan 15 2024 is MLK Day


def test_footnote_plan_flag_is_planned(session):
    make_issuer(session)
    make_filing(session)
    make_transaction(session, accession_no="0002000001-24-000001", plan_10b5_1="footnote")
    build_decisions(session)
    (d,) = _decisions(session)
    assert d.is_planned and d.plan_10b5_1 == "footnote"


def test_rebuild_replaces_only_given_issuers(session):
    make_issuer(session)
    make_issuer(session, cik=1000002, name="Globex Inc", ticker="GBX")
    make_filing(session, accession_no="0002000001-24-000001")
    make_filing(session, accession_no="0002000001-24-000002", issuer_cik=1000002)
    make_transaction(session, accession_no="0002000001-24-000001")
    make_transaction(session, accession_no="0002000001-24-000002", issuer_cik=1000002)
    assert build_decisions(session) == 2
    before = {d.issuer_cik: d.id for d in _decisions(session)}
    make_transaction(
        session,
        accession_no="0002000001-24-000001",
        row_no=2,
        code="S",
        shares_owned_after=10000.0,
    )
    assert build_decisions(session, issuer_ciks=[1000001]) == 2
    after = _decisions(session)
    assert [d.issuer_cik for d in after] == [1000001, 1000001, 1000002]
    assert after[-1].id == before[1000002]
    assert session.scalar(select(func.count()).select_from(DecisionOwner)) == 3
