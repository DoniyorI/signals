from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from signals.analytics.windows import beta_of, risk_label, window_stats
from signals.domain.calendars import trading_days


def nav_from_rows(
    *,
    dates: Sequence[date],
    nav: Sequence[float],
    spy: Sequence[float] | None = None,
    invested: Sequence[float] | None = None,
) -> pd.DataFrame:
    ones = [1.0] * len(dates)
    return pd.DataFrame(
        {
            "nav": [float(x) for x in nav],
            "spy": [float(x) for x in (spy if spy is not None else ones)],
            "qqq": ones,
            "sector": ones,
            "invested": [float(x) for x in (invested if invested is not None else ones)],
        },
        index=pd.Index(list(dates), dtype=object),
    )


def nav_from(values: dict[date, float]) -> pd.DataFrame:
    dates = sorted(values)
    return nav_from_rows(dates=dates, nav=[values[d] for d in dates])


def geometric_nav(end: date, n_returns: int, total: float) -> pd.DataFrame:
    """n_returns + 1 trading days ending at `end`, growing geometrically to `total`."""
    days = trading_days(end - timedelta(days=n_returns * 2), end)[-(n_returns + 1) :]
    assert len(days) == n_returns + 1
    step = total ** (1 / n_returns)
    return nav_from_rows(dates=days, nav=[step**i for i in range(n_returns + 1)])


def by_window(nav: pd.DataFrame, as_of: date) -> dict:
    return {x.window: x for x in window_stats(nav, as_of)}


def test_5y_doubling():
    nav = geometric_nav(end=date(2024, 12, 31), n_returns=1260, total=2.0)
    w = by_window(nav, date(2024, 12, 31))
    assert w["5y"].ret == pytest.approx(1.0)
    assert w["5y"].annualized == pytest.approx(0.148698, abs=1e-6)
    assert w["5y"].start == nav.index[0] and w["5y"].end == date(2024, 12, 31)
    assert w["1y"].ret == pytest.approx(2.0 ** (252 / 1260) - 1) and w["1y"].annualized is None


def test_windows_in_order():
    assert [
        x.window
        for x in window_stats(geometric_nav(date(2024, 12, 31), 300, 1.1), date(2024, 12, 31))
    ] == [
        "ytd",
        "1y",
        "3y",
        "5y",
    ]


def test_ytd_from_previous_year_close():
    nav = nav_from({date(2023, 12, 29): 1.0, date(2024, 6, 28): 1.1})
    ytd = by_window(nav, date(2024, 6, 28))["ytd"]
    assert ytd.ret == pytest.approx(0.10) and ytd.start == date(2023, 12, 29)


def test_ytd_none_without_previous_year_close():
    nav = nav_from({date(2024, 1, 2): 1.0, date(2024, 6, 28): 1.1})
    assert by_window(nav, date(2024, 6, 28))["ytd"].ret is None


def test_as_of_cuts_the_frame():
    nav = nav_from({date(2023, 12, 29): 1.0, date(2024, 6, 28): 1.1, date(2024, 7, 1): 2.0})
    assert by_window(nav, date(2024, 6, 30))["ytd"].ret == pytest.approx(0.10)


def test_short_history_none():
    w = by_window(geometric_nav(date(2024, 12, 31), 300, 1.1), date(2024, 12, 31))
    assert w["3y"].ret is None and w["5y"].ret is None and w["1y"].ret is not None
    assert (w["5y"].start, w["5y"].end, w["5y"].vol, w["5y"].annualized) == (None, None, None, None)


def test_drawdown_beta_invested():
    dates = [date(2023, 12, 29), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    nav = nav_from_rows(
        dates=dates, nav=[1, 1.2, 0.9, 1.1], spy=[1, 1.1, 0.95, 1.05], invested=[0, 1, 1, 0]
    )
    ytd = by_window(nav, date(2024, 1, 4))["ytd"]  # the YTD window spans all 4 rows
    assert ytd.max_drawdown == pytest.approx(-0.25) and ytd.time_invested_pct == pytest.approx(0.5)
    assert ytd.ret_spy == pytest.approx(0.05) and ytd.ret_qqq == pytest.approx(0.0)
    r = pd.Series([0.01, -0.02, 0.03])
    assert beta_of(2 * r, r) == pytest.approx(2.0)


def test_vol_is_annualized_sample_std():
    dates = [date(2023, 12, 29), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    nav = nav_from_rows(dates=dates, nav=[1.0, 1.01, 1.01 * 0.99, 1.01 * 0.99 * 1.02])
    ytd = by_window(nav, date(2024, 1, 4))["ytd"]
    assert ytd.vol == pytest.approx(0.0152753 * 252**0.5, rel=1e-4)
    assert ytd.beta is None  # SPY flat: no variance to regress on


def test_beta_of_ignores_missing_and_flat():
    assert beta_of(
        np.array([0.01, np.nan, 0.02, 0.0]), np.array([0.01, 0.03, 0.02, 0.0])
    ) == pytest.approx(1.0)
    assert beta_of(pd.Series([0.01, 0.02]), pd.Series([0.0, 0.0])) is None


def test_empty_nav_gives_four_empty_windows():
    w = window_stats(nav_from({}), date(2024, 12, 31))
    assert len(w) == 4 and all(x.ret is None and x.vol is None for x in w)


@pytest.mark.parametrize(
    "v,label", [(0.19, "low"), (0.20, "medium"), (0.40, "medium"), (0.41, "high"), (None, None)]
)
def test_risk_label(v, label):
    assert risk_label(v) == label
