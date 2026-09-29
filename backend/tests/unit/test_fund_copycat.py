from datetime import date
from typing import Literal

import pandas as pd
import pytest

from signals.analytics.funds import FundPeriodHoldings, fund_copycat_nav, fund_quarterly_excess
from signals.analytics.series import BenchPanel, IssuerSeries
from tests.analytics_support import bench_of, series_on_days

D0, D1, D2, D3, D4 = (date(2024, 1, d) for d in (2, 3, 4, 5, 8))
Q1, Q2 = date(2023, 12, 31), date(2024, 3, 31)


def _s(closes: list[float], opens: list[float] | None = None) -> IssuerSeries:
    return series_on_days(D0, closes, opens=opens)


def _period(
    start: date,
    weights: dict[str, float],
    *,
    kind: Literal["open", "close"] = "close",
    coverage: float = 1.0,
    period: date = Q1,
) -> FundPeriodHoldings:
    return FundPeriodHoldings(
        period=period, start=start, start_kind=kind, weights=weights, coverage=coverage
    )


@pytest.fixture
def flat_bench() -> BenchPanel:
    return bench_of(SPY=_s([100.0] * 5), QQQ=_s([100.0] * 5))


def _at(nav: pd.DataFrame, d: date, column: str = "nav") -> float:
    return float(nav[column][d])


def test_two_stocks_half_each(flat_bench):
    panel = {"A": _s([10.0, 11.0, 12.0]), "B": _s([10.0, 10.0, 10.0])}
    nav = fund_copycat_nav([_period(D0, {"A": 0.5, "B": 0.5})], panel, flat_bench, end=D2)
    assert list(nav.index) == [D0, D1, D2]
    assert _at(nav, D0) == 1.0 and _at(nav, D2) == pytest.approx(1.10)


def test_buy_and_hold_lets_weights_drift(flat_bench):
    panel = {"A": _s([10.0, 20.0, 10.0]), "B": _s([10.0, 10.0, 10.0])}
    nav = fund_copycat_nav([_period(D0, {"A": 0.5, "B": 0.5})], panel, flat_bench, end=D2)
    assert list(nav["nav"].round(9)) == [1.0, 1.5, 1.0]  # a daily-rebalanced mix would end at 1.125


def test_rebalance_next_period(flat_bench):
    panel = {"A": _s([10.0, 11.0, 12.0, 12.0, 12.0]), "B": _s([10.0, 10.0, 10.0, 10.5, 11.0])}
    periods = [_period(D0, {"A": 0.5, "B": 0.5}), _period(D2, {"B": 1.0}, period=Q2)]
    nav = fund_copycat_nav(periods, panel, flat_bench, end=D4)
    assert _at(nav, D2) == pytest.approx(1.10) and _at(nav, D4) == pytest.approx(1.21)


def test_open_start_buys_at_the_open(flat_bench):
    panel = {"A": _s([10.0, 11.0, 11.0], opens=[10.0, 10.0, 11.0])}
    nav = fund_copycat_nav([_period(D1, {"A": 1.0}, kind="open")], panel, flat_bench, end=D2)
    assert list(nav.index) == [D0, D1, D2]  # starts the session before, at 1.0
    assert _at(nav, D0) == 1.0 and _at(nav, D1) == pytest.approx(1.10)


def test_open_rebalance_sells_old_holdings_at_the_open(flat_bench):
    panel = {
        "A": _s([10.0, 11.0, 12.0, 13.0], opens=[10.0, 11.0, 12.0, 13.0]),
        "B": _s([10.0, 10.0, 10.0, 10.5], opens=[10.0, 10.0, 10.0, 10.0]),
    }
    periods = [_period(D0, {"A": 1.0}), _period(D3, {"B": 1.0}, kind="open", period=Q2)]
    nav = fund_copycat_nav(periods, panel, flat_bench, end=D3)
    assert _at(nav, D2) == pytest.approx(1.2)
    assert _at(nav, D3) == pytest.approx(1.2 * 13.0 / 12.0 * 10.5 / 10.0)


def test_prices_that_stop_are_carried(flat_bench):
    panel = {"A": _s([10.0, 12.0]), "B": _s([10.0, 10.0, 10.0, 11.0])}
    nav = fund_copycat_nav([_period(D0, {"A": 0.5, "B": 0.5})], panel, flat_bench, end=D3)
    assert _at(nav, D2) == pytest.approx(1.10) and _at(nav, D3) == pytest.approx(0.6 + 0.55)


def test_holding_first_priced_after_the_start_is_flat_until_then(flat_bench):
    panel = {"A": _s([10.0, 10.0, 12.0]), "B": series_on_days(D1, [20.0, 30.0])}
    nav = fund_copycat_nav([_period(D0, {"A": 0.5, "B": 0.5})], panel, flat_bench, end=D2)
    assert list(nav["nav"].round(9)) == [1.0, 1.0, 0.5 * 1.2 + 0.5 * 1.5]


def test_benchmarks_sector_and_coverage():
    bench = bench_of(
        SPY=_s([100.0, 101.0, 102.0]),
        QQQ=_s([100.0, 100.0, 100.0]),
        XLK=_s([50.0, 55.0, 55.0]),
    )
    panel = {"A": _s([10.0, 10.0, 10.0]), "B": _s([10.0, 10.0, 10.0])}
    periods = [
        _period(D0, {"A": 0.5, "B": 0.5}, coverage=0.8),
        _period(D1, {"A": 0.5, "B": 0.5}, coverage=0.6, period=Q2),
    ]
    nav = fund_copycat_nav(periods, panel, bench, end=D2, sector_etfs={"A": "XLK", "B": None})
    assert _at(nav, D2, "spy") == pytest.approx(1.02) and _at(nav, D2, "qqq") == 1.0
    assert _at(nav, D1, "sector") == pytest.approx(0.5 * 1.1 + 0.5 * 1.01)
    assert list(nav["coverage"]) == [0.8, 0.6, 0.6]


def test_sector_etf_without_history_at_the_start_uses_spy():
    bench = bench_of(
        SPY=_s([100.0, 102.0, 104.0]),
        QQQ=_s([100.0, 100.0, 100.0]),
        XLC=series_on_days(D1, [50.0, 60.0]),  # no bar yet when the period starts
    )
    panel = {"A": _s([10.0, 10.0, 10.0])}
    nav = fund_copycat_nav(
        [_period(D0, {"A": 1.0})], panel, bench, end=D2, sector_etfs={"A": "XLC"}
    )
    assert list(nav["sector"].round(9)) == [1.0, 1.02, 1.04]


def test_period_starting_after_end_is_ignored(flat_bench):
    panel = {"A": _s([10.0, 11.0, 12.0, 12.0]), "B": _s([10.0, 10.0, 10.0, 10.0])}
    periods = [_period(D0, {"A": 1.0}), _period(D3, {"B": 1.0}, period=Q2)]
    nav = fund_copycat_nav(periods, panel, flat_bench, end=D2)
    assert list(nav.index) == [D0, D1, D2] and _at(nav, D2) == pytest.approx(1.2)


def test_no_periods_is_empty(flat_bench):
    assert fund_copycat_nav([], {}, flat_bench, end=D4).empty


def test_quarterly_excess():
    nav = pd.DataFrame(
        {"nav": [1.0, 1.02, 1.05, 1.06], "spy": [1.0, 1.01, 1.02, 1.03]},
        index=pd.Index([D0, D1, D2, D3], dtype=object),
    )
    assert fund_quarterly_excess(nav, [D0, D2]) == [pytest.approx(0.03)]
    assert fund_quarterly_excess(nav, [D0]) == []  # the last period has no complete quarter yet
    assert fund_quarterly_excess(nav, [D0, D2, D4]) == [pytest.approx(0.03)]  # D4: after the data
