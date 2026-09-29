"""Decision badges (spec 9.8) on factory-seeded decisions."""

from datetime import date, datetime, time

from sqlalchemy import select

from signals.analytics.badges import compute_badges
from signals.analytics.decisions import build_decisions
from signals.db.models import Decision, Form144Notice, Owner, OwnerRole
from signals.domain.calendars import ET, add_trading_days, prev_trading_day, trading_days
from tests.factories import (
    make_decision,
    make_filing,
    make_issuer,
    make_owner,
    make_prices,
    make_transaction,
)


def _badges(session, decision: Decision) -> list[str]:
    session.expire_all()
    row = session.get(Decision, decision.id)
    assert row is not None
    return list(row.badges)


def _has(session, badge: str, *decisions: Decision) -> list[bool]:
    return [badge in _badges(session, d) for d in decisions]


# ----------------------------------------------------------------------------- cluster_buy
def test_cluster_three_groups_within_14_days(session):
    buys = [
        make_decision(session, owner_ciks=(cik,), first_trade_date=day)
        for cik, day in (
            (2000001, date(2024, 5, 1)),
            (2000002, date(2024, 5, 8)),
            (2000003, date(2024, 5, 14)),
        )
    ]
    compute_badges(session)
    assert _has(session, "cluster_buy", *buys) == [True, True, True]


def test_cluster_needs_window_of_14_days(session):
    buys = [
        make_decision(session, owner_ciks=(cik,), first_trade_date=day)
        for cik, day in (
            (2000001, date(2024, 5, 1)),
            (2000002, date(2024, 5, 8)),
            (2000003, date(2024, 5, 16)),
        )
    ]
    compute_badges(session)
    assert _has(session, "cluster_buy", *buys) == [False, False, False]


def test_joint_group_counts_once(session):
    joint = make_decision(session, owner_ciks=(2000003, 2000004), first_trade_date=date(2024, 5, 1))
    single = make_decision(session, owner_ciks=(2000001,), first_trade_date=date(2024, 5, 6))
    compute_badges(session)
    assert _has(session, "cluster_buy", joint, single) == [False, False]  # 3 owners, 2 groups


def test_cluster_counts_discretionary_buys_only(session):
    buys = [
        make_decision(session, owner_ciks=(2000001,), first_trade_date=date(2024, 5, 1)),
        make_decision(session, owner_ciks=(2000002,), first_trade_date=date(2024, 5, 2)),
    ]
    planned = make_decision(
        session, owner_ciks=(2000003,), first_trade_date=date(2024, 5, 3), plan_10b5_1="flag"
    )
    sale = make_decision(
        session, owner_ciks=(2000004,), first_trade_date=date(2024, 5, 3), direction="sell"
    )
    compute_badges(session)
    assert _has(session, "cluster_buy", *buys, planned, sale) == [False] * 4


# ----------------------------------------------------------------------------- late_filing
def test_late_filing_columbus_day(session):
    # Thu 2024-10-10; SEC closes Mon 10-14 (Columbus Day), so 10-15 is the 2nd business day
    on_time = make_decision(
        session,
        owner_ciks=(2000001,),
        first_trade_date=date(2024, 10, 10),
        accepted_at=datetime(2024, 10, 15, 12, 0, tzinfo=ET),
    )
    late = make_decision(
        session,
        owner_ciks=(2000002,),
        first_trade_date=date(2024, 10, 10),
        accepted_at=datetime(2024, 10, 16, 12, 0, tzinfo=ET),
    )
    compute_badges(session)
    assert _has(session, "late_filing", on_time, late) == [False, True]


def test_late_filing_without_acceptance_uses_filing_date(session):
    d = make_decision(session, first_trade_date=date(2024, 10, 10), accepted_at=None)
    d.filed_date = date(2024, 10, 16)
    session.flush()
    compute_badges(session)
    assert _has(session, "late_filing", d) == [True]


def test_late_filing_counts_from_deemed_execution_date(session):
    # Trade Tue 2024-10-01, accepted Mon 10-07: the 4th SEC business day after the trade,
    # but only the 2nd after a deemed execution date of Thu 10-03.
    make_issuer(session)
    for owner in (2000001, 2000002):
        acc = f"{owner:010d}-24-000010"
        make_filing(
            session,
            accession_no=acc,
            filed_date=date(2024, 10, 7),
            accepted_at=datetime(2024, 10, 7, 12, 0, tzinfo=ET),
            owners=(owner,),
        )
        tx = make_transaction(
            session, accession_no=acc, owner_ciks=(owner,), transaction_date=date(2024, 10, 1)
        )
        if owner == 2000001:
            tx.deemed_execution_date = date(2024, 10, 3)
    session.flush()
    build_decisions(session)

    compute_badges(session)

    late = {d.owner_group: "late_filing" in d.badges for d in session.scalars(select(Decision))}
    assert late == {"2000001": False, "2000002": True}


# ----------------------------------------------------------------------------- first_buy_2y
def test_first_buy_2y(session):
    make_decision(session, owner_ciks=(2000001,), first_trade_date=date(2022, 5, 1))
    after_732_days = make_decision(
        session, owner_ciks=(2000001,), first_trade_date=date(2024, 5, 2)
    )
    make_decision(session, owner_ciks=(2000002,), first_trade_date=date(2022, 6, 1))
    after_701_days = make_decision(
        session, owner_ciks=(2000002,), first_trade_date=date(2024, 5, 2)
    )
    compute_badges(session)
    assert _has(session, "first_buy_2y", after_732_days, after_701_days) == [True, False]


def test_first_buy_2y_counts_discretionary_buys_only(session):
    planned = make_decision(session, first_trade_date=date(2024, 1, 10), plan_10b5_1="flag")
    make_decision(session, first_trade_date=date(2024, 3, 1), direction="sell")
    buy = make_decision(session, first_trade_date=date(2024, 5, 2))
    compute_badges(session)
    assert _has(session, "first_buy_2y", planned, buy) == [False, True]


# ----------------------------------------------------------------------------- dip_buy
DIP_TRADE = date(2024, 5, 15)


def _dip_issuer(session, cik: int, symbol: str, drop: float) -> None:
    """Closes at 100 through the day 60 sessions before the pre-trade close, then 100 x
    (1 - drop)."""
    make_issuer(session, cik=cik, name=symbol, ticker=symbol)
    start = add_trading_days(prev_trading_day(DIP_TRADE), -60)
    days = trading_days(date(2024, 1, 2), DIP_TRADE)
    make_prices(
        session, symbol, days[0], [100.0 if d <= start else 100.0 * (1 - drop) for d in days]
    )


def test_dip_buy_threshold(session):
    for cik, symbol, drop in (
        (1000001, "AAA", 0.21),
        (1000002, "BBB", 0.19),
        (1000003, "CCC", 0.20),
    ):
        _dip_issuer(session, cik, symbol, drop)
    fell_21, fell_19, fell_20 = (
        make_decision(session, issuer_cik=cik, first_trade_date=DIP_TRADE)
        for cik in (1000001, 1000002, 1000003)
    )
    sale = make_decision(
        session,
        owner_ciks=(2000002,),
        issuer_cik=1000001,
        first_trade_date=DIP_TRADE,
        direction="sell",
    )
    compute_badges(session)
    # "fell 20% or more": exactly 20% counts
    assert _has(session, "dip_buy", fell_21, fell_19, fell_20, sale) == [True, False, True, False]


# ----------------------------------------------------------------------------- big_stake
def test_big_stake(session):
    def buy(owner: int, *, value_usd: float = 10_000.0, **facts: object) -> Decision:
        d = make_decision(session, owner_ciks=(owner,), value_usd=value_usd)
        for name, value in facts.items():
            setattr(d, name, value)
        session.flush()
        return d

    stake_20 = buy(2000001, stake_change_pct=0.2)
    under_both = buy(2000002, stake_change_pct=0.19, value_usd=999_999.0)
    million = buy(2000003, stake_change_pct=0.01, value_usd=1_000_000.0)
    new_position = buy(2000004, is_new_position=True)
    sale = make_decision(session, owner_ciks=(2000005,), direction="sell", value_usd=5_000_000.0)
    compute_badges(session)
    assert _has(session, "big_stake", stake_20, under_both, million, new_position, sale) == [
        True,
        False,
        True,
        True,
        False,
    ]


# ----------------------------------------------------------------------------- form144_matched
def _notice(session, accession_no: str, filed: date, *, filer: int = 2000001) -> None:
    make_filing(
        session,
        accession_no=accession_no,
        form_type="144",
        filed_date=filed,
        accepted_at=datetime.combine(filed, time(10, 0), ET),
        owners=(filer,),
    )
    session.add(Form144Notice(accession_no=accession_no, filer_cik=filer, issuer_cik=1000001))
    session.flush()


def _matched(session, accession_no: str) -> str | None:
    session.expire_all()
    notice = session.get(Form144Notice, accession_no)
    assert notice is not None
    return notice.matched_sale_accession


def test_form144_match_window(session):
    _notice(session, "0002000001-24-000144", date(2024, 3, 1))  # window 03-01 .. 05-30

    def sale(day: date, owner: int = 2000001) -> Decision:
        return make_decision(session, owner_ciks=(owner,), direction="sell", first_trade_date=day)

    before = sale(date(2024, 2, 29))
    first = sale(date(2024, 4, 15))
    last_day = sale(date(2024, 5, 30))
    after = sale(date(2024, 5, 31))
    far = sale(date(2024, 6, 15))
    other_owner = sale(date(2024, 4, 16), owner=2000002)
    compute_badges(session)
    assert _has(session, "form144_matched", before, first, last_day, after, far, other_owner) == [
        False,
        True,
        True,
        False,
        False,
        False,
    ]
    assert _matched(session, "0002000001-24-000144") == first.first_accession  # earliest wins


def test_form144_stale_match_cleared(session):
    _notice(session, "0002000001-24-000144", date(2024, 3, 1))
    notice = session.get(Form144Notice, "0002000001-24-000144")
    assert notice is not None
    notice.matched_sale_accession = "0002000001-24-000999"
    session.flush()
    compute_badges(session)
    assert _matched(session, "0002000001-24-000144") is None


# ----------------------------------------------------------------------------- top_exec
def test_top_exec_from_roles(session):
    make_issuer(session)
    make_issuer(session, cik=1000002, name="Other Corp", ticker="OTHR")
    for owner, issuer, roles in (
        (2000001, 1000001, ["CEO"]),
        (2000002, 1000001, ["Director"]),
        (2000003, 1000002, ["CEO"]),
        (2000004, 1000001, ["CFO", "Director"]),
    ):
        if session.get(Owner, owner) is None:
            make_owner(session, cik=owner, name=f"Owner {owner}")
        session.add(OwnerRole(owner_cik=owner, issuer_cik=issuer, roles=roles))
    session.flush()
    ceo = make_decision(session, owner_ciks=(2000001,))
    ceo_sale = make_decision(session, owner_ciks=(2000001,), direction="sell")
    director = make_decision(session, owner_ciks=(2000002,))
    ceo_elsewhere = make_decision(session, owner_ciks=(2000003,))
    joint_with_cfo = make_decision(session, owner_ciks=(2000004, 2000005))
    compute_badges(session)
    assert _has(session, "top_exec", ceo, ceo_sale, director, ceo_elsewhere, joint_with_cfo) == [
        True,
        True,
        False,
        False,
        True,
    ]


# ----------------------------------------------------------------------------- scope and count
def test_counts_changed_decisions_within_issuer_scope(session):
    cluster = [
        make_decision(
            session, owner_ciks=(cik,), issuer_cik=1000002, first_trade_date=date(2024, 5, 1)
        )
        for cik in (2000001, 2000002, 2000003)
    ]
    outside = make_decision(
        session, owner_ciks=(2000009,), issuer_cik=1000001, first_trade_date=date(2024, 5, 1)
    )

    assert compute_badges(session, issuer_ciks=[1000002]) == 3
    assert _has(session, "cluster_buy", *cluster) == [True, True, True]
    assert _badges(session, outside) == []
    assert compute_badges(session, issuer_ciks=[1000002]) == 0  # a rerun changes nothing
