from datetime import date

import pytest
from sqlalchemy import func, select

from signals.db.models import FundManager, FundPositionChange
from signals.domain.appstate import get_state
from signals.ingest.fund_changes import (
    compute_fund_changes,
    flag_value_unit_anomalies,
    refresh_fund_manager_stats,
)
from tests.factories import (
    make_fund_filing,
    make_fund_manager,
    make_fund_position,
    make_issuer,
    make_prices,
    make_security,
)

FILER = 3000001
Q1, Q2, Q3 = date(2024, 3, 31), date(2024, 6, 30), date(2024, 9, 30)


def seed_two_quarters(session) -> None:
    make_fund_manager(session)
    q1 = make_fund_filing(session, accession_no="0003000001-24-000001", period=Q1)
    q2 = make_fund_filing(
        session, accession_no="0003000001-24-000002", period=Q2, filed_date=date(2024, 8, 14)
    )
    for cusip, sh in [("000000AA1", 100), ("000000BB2", 50), ("000000CC3", 10)]:
        make_fund_position(
            session,
            accession_no=q1.accession_no,
            period=Q1,
            cusip=cusip,
            shares=sh,
            value_usd=sh * 10.0,
        )
    for cusip, sh in [("000000AA1", 150), ("000000BB2", 50), ("000000DD4", 20)]:
        make_fund_position(
            session,
            accession_no=q2.accession_no,
            period=Q2,
            cusip=cusip,
            shares=sh,
            value_usd=sh * 10.0,
        )


def _changes(session, period: date) -> dict[tuple[str, str], FundPositionChange]:
    rows = session.scalars(select(FundPositionChange).where(FundPositionChange.period == period))
    return {(r.cusip, r.put_call): r for r in rows}


def test_changes_new_add_same_exit(session):
    seed_two_quarters(session)
    written = compute_fund_changes(session, filer_ciks=[FILER])
    rows = {c: r for (c, _), r in _changes(session, Q2).items()}
    assert (rows["000000AA1"].change, rows["000000AA1"].shares_change_pct) == ("ADD", 0.5)
    assert rows["000000BB2"].change == "SAME" and rows["000000BB2"].shares_change_pct == 0.0
    assert rows["000000CC3"].change == "EXIT" and rows["000000CC3"].shares == 0
    assert rows["000000DD4"].change == "NEW"
    assert rows["000000AA1"].weight == pytest.approx(1500 / 2200)
    assert written == 3 + 4  # Q1: three NEW rows; Q2: ADD, SAME, EXIT, NEW


def test_change_details(session):
    seed_two_quarters(session)
    compute_fund_changes(session, filer_ciks=[FILER])
    q1 = _changes(session, Q1)
    assert {r.change for r in q1.values()} == {"NEW"}
    assert all(r.prev_shares is None and r.prev_weight is None for r in q1.values())
    q2 = {c: r for (c, _), r in _changes(session, Q2).items()}
    aa, cc, dd = q2["000000AA1"], q2["000000CC3"], q2["000000DD4"]
    assert (aa.prev_shares, aa.shares, aa.value_usd) == (100.0, 150.0, 1500.0)
    assert aa.prev_weight == pytest.approx(1000 / 1600)
    assert (cc.prev_shares, cc.value_usd, cc.weight, cc.shares_change_pct) == (10.0, 0.0, 0.0, -1.0)
    assert cc.prev_weight == pytest.approx(100 / 1600)
    assert (dd.prev_shares, dd.shares_change_pct, dd.prev_weight) == (None, None, None)
    assert dd.weight == pytest.approx(200 / 2200)


def test_trim_and_options_weight(session):
    seed_two_quarters(session)
    q3 = make_fund_filing(
        session, accession_no="0003000001-24-000003", period=Q3, filed_date=date(2024, 11, 14)
    )
    make_fund_position(
        session,
        accession_no=q3.accession_no,
        period=Q3,
        cusip="000000AA1",
        shares=60,
        value_usd=600,
    )
    make_fund_position(
        session,
        accession_no=q3.accession_no,
        period=Q3,
        cusip="000000AA1",
        put_call="CALL",
        shares=1000,
        value_usd=10_000,
    )
    compute_fund_changes(session, filer_ciks=[FILER])
    q3_rows = _changes(session, Q3)
    stock, call = q3_rows[("000000AA1", "")], q3_rows[("000000AA1", "CALL")]
    assert (stock.change, stock.shares_change_pct) == ("TRIM", pytest.approx(-0.6))
    assert stock.weight == pytest.approx(1.0)  # options never enter the denominator
    assert (call.change, call.weight, call.prev_weight) == ("NEW", None, None)
    assert q3_rows[("000000BB2", "")].change == "EXIT"


def test_previous_is_latest_period_with_positions(session):
    seed_two_quarters(session)
    # Q3 is skipped; Q4 compares against Q2.
    q4 = make_fund_filing(
        session,
        accession_no="0003000001-25-000001",
        period=date(2024, 12, 31),
        filed_date=date(2025, 2, 14),
    )
    make_fund_position(
        session,
        accession_no=q4.accession_no,
        period=date(2024, 12, 31),
        cusip="000000DD4",
        shares=20,
        value_usd=200,
    )
    compute_fund_changes(session, filer_ciks=[FILER])
    rows = {c: r.change for (c, _), r in _changes(session, date(2024, 12, 31)).items()}
    assert rows == {"000000AA1": "EXIT", "000000BB2": "EXIT", "000000DD4": "SAME"}


def test_ignores_positions_that_are_not_effective(session):
    seed_two_quarters(session)
    old = make_fund_filing(
        session, accession_no="0003000001-24-000009", period=Q2, filed_date=date(2024, 8, 1)
    )
    make_fund_position(
        session, accession_no=old.accession_no, period=Q2, cusip="000000ZZ9", is_effective=False
    )
    compute_fund_changes(session, filer_ciks=[FILER])
    assert ("000000ZZ9", "") not in _changes(session, Q2)


def test_sums_effective_rows_across_amendments(session):
    seed_two_quarters(session)
    add = make_fund_filing(
        session,
        accession_no="0003000001-24-000005",
        period=Q2,
        filed_date=date(2024, 9, 1),
        submission_type="13F-HR/A",
        amendment_type="NEW HOLDINGS",
    )
    make_fund_position(
        session, accession_no=add.accession_no, period=Q2, cusip="000000BB2", shares=5, value_usd=50
    )
    compute_fund_changes(session, filer_ciks=[FILER])
    bb = _changes(session, Q2)[("000000BB2", "")]
    assert (bb.shares, bb.change, bb.value_usd) == (55.0, "ADD", 550.0)


def test_replaces_rows_for_touched_keys(session):
    seed_two_quarters(session)
    compute_fund_changes(session, filer_ciks=[FILER])
    stale = FundPositionChange(filer_cik=FILER, period=Q2, cusip="STALE0001", change="NEW")
    other = FundPositionChange(filer_cik=FILER + 1, period=Q2, cusip="000000AA1", change="NEW")
    session.add_all([stale, other])
    session.flush()
    again = compute_fund_changes(session, filer_ciks=[FILER], periods=[Q2])
    assert again == 4
    q2 = _changes(session, Q2)
    assert ("STALE0001", "") not in q2 and len(q2) == 4
    kept = session.scalar(select(func.count()).where(FundPositionChange.filer_cik == FILER + 1))
    assert kept == 1 and len(_changes(session, Q1)) == 3


def test_manager_stats(session):
    seed_two_quarters(session)
    assert refresh_fund_manager_stats(session, filer_ciks=[FILER]) == 1
    m = session.get(FundManager, FILER)
    assert (m.latest_period, m.latest_value_usd, m.latest_positions) == (Q2, 2200.0, 3)


def test_manager_stats_count_stock_positions_only(session):
    seed_two_quarters(session)
    q2 = "0003000001-24-000002"
    make_fund_position(
        session, accession_no=q2, period=Q2, cusip="000000AA1", put_call="PUT", value_usd=300
    )
    assert refresh_fund_manager_stats(session) == 1
    m = session.get(FundManager, FILER)
    assert (m.latest_value_usd, m.latest_positions) == (2500.0, 3)


def _seed_priced_position(session, *, period: date, value_usd: float, shares: float = 100):
    make_issuer(session)
    make_security(session, cusip="000000AA1", ticker="ACME")
    make_prices(session, "ACME", date(2024, 3, 28), [10.0])
    make_fund_manager(session)
    f = make_fund_filing(session, period=period)
    make_fund_position(
        session,
        accession_no=f.accession_no,
        period=period,
        cusip="000000AA1",
        shares=shares,
        value_usd=value_usd,
    )
    return f


def test_unit_anomaly_flagged(session):
    f = _seed_priced_position(session, period=date(2024, 3, 28), value_usd=1_000_000)
    assert flag_value_unit_anomalies(session) == 1
    state = get_state(session, "f13f_unit_anomalies")
    assert state is not None and state["count"] == 1
    assert state["sample"] == [
        {
            "accession": f.accession_no,
            "cusip": "000000AA1",
            "period": "2024-03-28",
            "implied": 10000.0,
            "close": 10.0,
        }
    ]


def test_plausible_value_not_flagged(session):
    _seed_priced_position(session, period=date(2024, 3, 28), value_usd=1_000)
    assert flag_value_unit_anomalies(session) == 0
    assert get_state(session, "f13f_unit_anomalies") == {"count": 0, "sample": []}


def test_weekend_quarter_end_uses_last_close(session):
    # 2024-03-31 is a Sunday; the last close before it is Thursday 2024-03-28 (Good Friday).
    _seed_priced_position(session, period=date(2024, 3, 31), value_usd=1)
    assert flag_value_unit_anomalies(session) == 1  # implied 0.01 / close 10 = 0.001


def test_anomalies_period_filter(session):
    _seed_priced_position(session, period=date(2024, 3, 28), value_usd=1_000_000)
    assert flag_value_unit_anomalies(session, periods=[date(2023, 12, 29)]) == 0
    assert flag_value_unit_anomalies(session, periods=[date(2024, 3, 28)]) == 1
