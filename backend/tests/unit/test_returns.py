from datetime import date

import pytest

from signals.analytics.entries import Entry, executed_entry
from signals.analytics.returns import horizon_returns, lag_cost
from signals.analytics.series import BenchPanel, IssuerSeries
from signals.domain.calendars import trading_days
from tests.analytics_support import bench_of, series_from_bars

JAN2, FEB1, FEB14 = date(2024, 1, 2), date(2024, 2, 1), date(2024, 2, 14)


def _closes(days: list[date], close_of) -> IssuerSeries:
    return series_from_bars({d: (close_of(d), close_of(d), 1.0) for d in days})


@pytest.fixture
def stock() -> IssuerSeries:
    """100 until Jan 31, 110 from Feb 1 (21 trading days after Jan 2), last close 5 on Feb 14."""
    return _closes(
        trading_days(JAN2, FEB14),
        lambda d: 5.0 if d == FEB14 else 110.0 if d >= FEB1 else 100.0,
    )


@pytest.fixture
def bench() -> BenchPanel:
    days = trading_days(JAN2, date(2024, 12, 31))
    spy = series_from_bars(
        {d: (396.0 if d == JAN2 else 400.0, 404.0 if d >= FEB1 else 400.0, 1.0) for d in days}
    )
    qqq = _closes(days, lambda d: 300.0)
    return bench_of(SPY=spy, QQQ=qqq)


def test_buy_returns_and_excess(stock, bench):
    r = horizon_returns(Entry(JAN2, 100.0, "close"), "buy", stock, bench, None, date(2024, 12, 31))[
        0
    ]
    assert (r.horizon, r.exit_date, r.complete, r.exit_reason) == ("1m", FEB1, True, "horizon")
    assert r.raw == pytest.approx(0.10) and r.excess_spy == pytest.approx(0.09)
    assert r.excess_qqq == pytest.approx(0.10) and r.excess_sector is None


def test_four_horizons_in_order(stock, bench):
    rs = horizon_returns(Entry(JAN2, 100.0, "close"), "buy", stock, bench, None, date(2024, 12, 31))
    assert [r.horizon for r in rs] == ["1m", "3m", "6m", "12m"]


def test_sell_sign_flipped(stock, bench):
    r = horizon_returns(
        Entry(JAN2, 100.0, "close"), "sell", stock, bench, None, date(2024, 12, 31)
    )[0]
    assert r.raw == pytest.approx(-0.10) and r.excess_spy == pytest.approx(-0.09)


def test_benchmark_enters_at_open_for_open_entries(stock, bench):
    r = horizon_returns(Entry(JAN2, 100.0, "open"), "buy", stock, bench, None, date(2024, 12, 31))[
        0
    ]
    assert r.excess_spy == pytest.approx(0.10 - (404.0 / 396.0 - 1))


def test_incomplete_horizon(stock, bench):
    r = horizon_returns(Entry(JAN2, 100.0, "close"), "buy", stock, bench, None, date(2024, 1, 12))[
        0
    ]
    assert r.complete is False and r.exit_date == date(2024, 1, 12) and r.raw == pytest.approx(0.0)


def test_delisted_exit_at_last_price(stock, bench):
    r3 = horizon_returns(
        Entry(JAN2, 100.0, "close"), "buy", stock, bench, None, date(2024, 12, 31)
    )[1]
    assert (r3.exit_reason, r3.complete, r3.raw) == ("last_price", True, pytest.approx(-0.95))
    assert r3.exit_date == FEB14 and r3.excess_spy == pytest.approx(-0.95 - 0.01)


def test_not_delisted_when_market_data_ends_too(stock):
    # prices for everything stop on Feb 14 (e.g. the nightly run before today's bars load):
    # the 3m horizon is not observable yet, so it stays incomplete instead of "delisted"
    spy = _closes(trading_days(JAN2, FEB14), lambda d: 400.0)
    r3 = horizon_returns(
        Entry(JAN2, 100.0, "close"), "buy", stock, bench_of(SPY=spy), None, date(2024, 12, 31)
    )[1]
    assert (r3.complete, r3.exit_reason, r3.exit_date) == (False, "horizon", FEB14)


def test_exit_gap_uses_last_close_before_target(bench):
    days = [d for d in trading_days(JAN2, date(2024, 3, 1)) if d != FEB1]
    s = _closes(days, lambda d: 120.0 if d >= date(2024, 1, 31) else 100.0)
    r = horizon_returns(Entry(JAN2, 100.0, "close"), "buy", s, bench, None, date(2024, 12, 31))[0]
    assert (r.exit_date, r.complete, r.exit_reason) == (date(2024, 1, 31), True, "horizon")
    assert r.raw == pytest.approx(0.20) and "exit_gap" in r.flags


def test_missing_benchmark_bar_gives_none(stock):
    spy = _closes([d for d in trading_days(JAN2, date(2024, 12, 31)) if d != FEB1], lambda d: 400.0)
    r = horizon_returns(
        Entry(JAN2, 100.0, "close"), "buy", stock, bench_of(SPY=spy), "XLK", date(2024, 12, 31)
    )[0]
    assert r.raw == pytest.approx(0.10)
    assert (r.excess_spy, r.excess_qqq, r.excess_sector) == (None, None, None)


def test_sector_excess_none_before_etf_history():
    days = trading_days(date(2018, 1, 2), date(2018, 12, 31))
    stock2018 = _closes(days, lambda d: 55.0 if d > date(2018, 1, 2) else 50.0)
    bench_without_xlc = bench_of(
        SPY=_closes(days, lambda d: 100.0), QQQ=_closes(days, lambda d: 100.0)
    )
    r = horizon_returns(
        Entry(date(2018, 1, 2), 50.0, "close"),
        "buy",
        stock2018,
        bench_without_xlc,
        "XLC",
        date(2019, 1, 1),
    )[0]
    assert r.excess_sector is None and r.excess_spy == pytest.approx(0.10)


def test_sector_excess_with_etf(stock, bench):
    xlk = _closes(trading_days(JAN2, date(2024, 12, 31)), lambda d: 105.0 if d >= FEB1 else 100.0)
    panel = bench_of(**bench.series, XLK=xlk)
    r = horizon_returns(
        Entry(JAN2, 100.0, "close"), "buy", stock, panel, "XLK", date(2024, 12, 31)
    )[0]
    assert r.excess_sector == pytest.approx(0.05)


def test_returns_across_split(bench):
    # raw 200 with factor 0.5 on the entry day (adj 100); after a 2:1 split, raw 110 at factor 1
    bars = {}
    for d in trading_days(JAN2, date(2024, 3, 1)):
        if d < date(2024, 1, 16):
            bars[d] = (200.0, 200.0, 0.5)
        else:
            bars[d] = (110.0, 110.0, 1.0) if d >= FEB1 else (100.0, 100.0, 1.0)
    split_stock = series_from_bars(bars)
    e = executed_entry(JAN2, 200.0, split_stock)
    assert e is not None
    r = horizon_returns(e, "buy", split_stock, bench, None, date(2024, 12, 31))[0]
    assert e.price_adj == pytest.approx(100.0) and r.raw == pytest.approx(0.10)


def test_entry_after_as_of_has_no_returns(stock, bench):
    assert horizon_returns(Entry(FEB1, 110.0, "close"), "buy", stock, bench, None, JAN2) == []


def test_lag_cost():
    ex, fi = Entry(JAN2, 50.0, "reported"), Entry(date(2024, 1, 4), 55.0, "open")
    assert lag_cost("buy", fi, ex) == pytest.approx(0.10)
    assert lag_cost("sell", Entry(date(2024, 1, 4), 45.0, "open"), ex) == pytest.approx(0.10)
    assert lag_cost("buy", None, ex) is None and lag_cost("sell", fi, None) is None
