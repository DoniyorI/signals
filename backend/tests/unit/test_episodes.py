from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd
import pytest

from signals.analytics.decisions import group_episodes
from signals.domain.calendars import ET


def tx(
    d: date,
    code: str = "P",
    shares: float = 100.0,
    price: float | None = 10.0,
    after: float | None = 1100.0,
    group: str = "2000001",
    planned: bool = False,
    acc: str = "A1",
    order: int = 1,
) -> dict[str, Any]:
    return dict(
        tx_id=order,
        accession_no=acc,
        owner_group=group,
        owner_ciks=[int(g) for g in group.split("|")],
        issuer_cik=1000001,
        code=code,
        is_planned=planned,
        plan_10b5_1="flag" if planned else "none",
        transaction_date=d,
        shares=shares,
        price=price,
        shares_owned_after=after,
        row_order=order,
        accepted_at=datetime.combine(d, time(17, 0), ET) + timedelta(days=2),
        filed_date=d + timedelta(days=2),
    )


def test_within_10_trading_days_is_one_episode():
    df = group_episodes(
        pd.DataFrame(
            [tx(date(2024, 1, 2)), tx(date(2024, 1, 10), order=2), tx(date(2024, 1, 17), order=3)]
        )
    )
    assert len(df) == 1
    assert df.iloc[0].first_trade_date == date(2024, 1, 2)
    assert df.iloc[0].last_trade_date == date(2024, 1, 17)


def test_gap_over_10_trading_days_splits():
    rows = [tx(date(2024, 1, 2)), tx(date(2024, 1, 18), order=2)]
    assert len(group_episodes(pd.DataFrame(rows))) == 2


def test_planned_and_discretionary_never_merge():
    rows = [tx(date(2024, 1, 2)), tx(date(2024, 1, 3), planned=True, order=2)]
    assert len(group_episodes(pd.DataFrame(rows))) == 2


def test_buys_and_sells_never_merge():
    rows = [tx(date(2024, 1, 2)), tx(date(2024, 1, 3), code="S", after=1000.0, order=2)]
    df = group_episodes(pd.DataFrame(rows))
    assert sorted(df["direction"]) == ["buy", "sell"]


def test_vwap_first_day_only():
    rows = [
        tx(date(2024, 1, 2), shares=100, price=10),
        tx(date(2024, 1, 2), shares=300, price=12, order=2),
        tx(date(2024, 1, 3), shares=50, price=20, order=3),
    ]
    d = group_episodes(pd.DataFrame(rows)).iloc[0]
    assert d.vwap == pytest.approx(11.5)
    assert (d.shares, d.value_usd) == (450.0, pytest.approx(5600.0))


def test_value_and_vwap_skip_unpriced_rows():
    rows = [
        tx(date(2024, 1, 2), shares=100, price=None),
        tx(date(2024, 1, 3), shares=50, price=20, order=2),
    ]
    d = group_episodes(pd.DataFrame(rows)).iloc[0]
    assert d.vwap is None and d.value_usd == pytest.approx(1000.0) and d.shares == 150.0


def test_stake_change_and_new_position():
    a = group_episodes(pd.DataFrame([tx(date(2024, 1, 2), shares=200, after=1200)])).iloc[0]
    b = group_episodes(pd.DataFrame([tx(date(2024, 1, 2), shares=500, after=500)])).iloc[0]
    assert a.stake_change_pct == pytest.approx(0.2) and not a.is_new_position
    assert b.is_new_position and b.stake_change_pct is None


def test_inconsistent_owned_after_leaves_stake_unknown():
    # owned-after below the shares bought: the prior holding is unknowable, not zero
    c = group_episodes(pd.DataFrame([tx(date(2024, 1, 2), shares=500, after=300)])).iloc[0]
    d = group_episodes(pd.DataFrame([tx(date(2024, 1, 2), shares=500, after=None)])).iloc[0]
    for row in (c, d):
        assert row.stake_change_pct is None and not row.is_new_position


def test_sell_fraction_multi_row():
    rows = [
        tx(date(2024, 1, 2), code="S", shares=100, after=900),
        tx(date(2024, 1, 3), code="S", shares=150, after=750, order=2),
    ]
    d = group_episodes(pd.DataFrame(rows)).iloc[0]
    assert d.sell_fraction == pytest.approx(0.25) and d.direction == "sell"
    assert d.stake_change_pct is None and not d.is_new_position


def test_lag_days_sec_business_days():
    r = tx(date(2024, 10, 11))
    r["accepted_at"] = datetime(2024, 10, 16, 17, 0, tzinfo=ET)
    assert group_episodes(pd.DataFrame([r])).iloc[0].lag_days == 2


def test_lag_days_from_filed_date_when_acceptance_unknown():
    r = tx(date(2024, 10, 11))
    r["accepted_at"], r["filed_date"] = None, date(2024, 10, 17)
    d = group_episodes(pd.DataFrame([r])).iloc[0]
    assert d.lag_days == 3 and d.accepted_at is None and d.filed_date == date(2024, 10, 17)


def test_first_accession_is_earliest_accepted_filing():
    early_trade = tx(date(2024, 1, 2), acc="A2")
    early_trade["accepted_at"] = datetime(2024, 1, 9, 9, 0, tzinfo=ET)
    later_trade = tx(date(2024, 1, 3), acc="A1", order=2)
    later_trade["accepted_at"] = datetime(2024, 1, 5, 18, 0, tzinfo=ET)
    d = group_episodes(pd.DataFrame([early_trade, later_trade])).iloc[0]
    assert d.first_accession == "A1" and d.accessions == ["A1", "A2"]
    assert d.accepted_at == datetime(2024, 1, 5, 18, 0, tzinfo=ET)
    assert d.filed_date == date(2024, 1, 5)


def test_owner_group_and_planned_flag_carried():
    rows = [tx(date(2024, 1, 2), group="2000003|2000004", planned=True)]
    d = group_episodes(pd.DataFrame(rows)).iloc[0]
    assert d.owner_ciks == [2000003, 2000004] and d.is_planned and d.plan_10b5_1 == "flag"


def test_empty_input():
    assert group_episodes(pd.DataFrame([])).empty
