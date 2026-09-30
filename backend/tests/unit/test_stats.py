from collections.abc import Sequence

import pandas as pd
import pytest

from signals.analytics.stats import (
    confidence_fund,
    confidence_insider,
    percentile_ratings,
    shrunk_mean,
    summarize,
)


def decisions_df(
    ids: Sequence[int],
    *,
    directions: Sequence[str] | None = None,
    lag_days: Sequence[float | None] | None = None,
    lag_costs: Sequence[float | None] | None = None,
) -> pd.DataFrame:
    n = len(ids)
    return pd.DataFrame(
        {
            "id": list(ids),
            "direction": list(directions) if directions is not None else ["buy"] * n,
            "lag_days": list(lag_days) if lag_days is not None else [None] * n,
            "lag_cost": list(lag_costs) if lag_costs is not None else [None] * n,
        }
    )


def returns_df(rows: Sequence[tuple[int, float | None, float | None, bool]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["decision_id", "raw_return", "excess_spy", "is_complete"])


def test_shrunk_mean():
    assert shrunk_mean(2, 0.10, 0.01, 5) == pytest.approx(0.0357142857)
    assert shrunk_mean(40, 0.10, 0.01, 5) == pytest.approx(0.09)


def test_percentile_ratings():
    assert list(percentile_ratings(pd.Series([0.01, 0.02, 0.03]))) == [0, 50, 100]
    assert list(percentile_ratings(pd.Series([0.5]))) == [50]
    assert percentile_ratings(pd.Series([0.1, float("nan")])).isna().tolist() == [False, True]


def test_percentile_ratings_average_ties():
    assert list(percentile_ratings(pd.Series([0.3, 0.1, 0.1]))) == [100, 25, 25]


@pytest.mark.parametrize(
    "n,c", [(0, None), (4, "low"), (5, "medium"), (15, "medium"), (16, "high")]
)
def test_confidence_insider(n, c):
    assert confidence_insider(n) == c


@pytest.mark.parametrize(
    "n,c", [(0, None), (3, "low"), (4, "medium"), (12, "medium"), (13, "high")]
)
def test_confidence_fund(n, c):
    assert confidence_fund(n) == c


def test_summary_values():
    s = summarize(
        decisions_df(ids=[1, 2, 3, 4]),
        returns_df(
            [
                (1, 0.12, 0.10, True),
                (2, -0.03, -0.05, True),
                (3, 0.04, 0.02, True),
                (4, 0.5, 0.4, False),
            ]
        ),
    )
    assert s.n_complete == 3 and s.avg_roi_6m == pytest.approx(0.0233333, abs=1e-6)
    assert s.hit_rate == pytest.approx(2 / 3) and s.median_6m == pytest.approx(0.02)
    assert (s.best_decision_id, s.worst_decision_id) == (1, 2)


def test_summary_counts_raw_mean_and_lags():
    s = summarize(
        decisions_df(
            ids=[1, 2, 3],
            directions=["buy", "sell", "buy"],
            lag_days=[2, 5, None],
            lag_costs=[0.01, None, 0.03],
        ),
        returns_df([(1, 0.12, 0.10, True), (2, -0.04, 0.02, True), (9, 0.9, 0.9, True)]),
    )
    assert (s.n_decisions, s.n_buys, s.n_sells, s.n_complete) == (3, 2, 1, 2)
    assert s.avg_roi_6m_raw == pytest.approx(0.04)  # decision 9 is not in this profile
    assert s.avg_lag_days == pytest.approx(3.5) and s.avg_lag_cost == pytest.approx(0.02)


def test_summary_without_complete_decisions():
    s = summarize(decisions_df(ids=[1]), returns_df([(1, 0.5, None, True), (1, 0.4, 0.3, False)]))
    assert (s.n_decisions, s.n_complete) == (1, 0)
    assert (s.avg_roi_6m, s.avg_roi_6m_raw, s.median_6m, s.hit_rate) == (None, None, None, None)
    assert (s.best_decision_id, s.worst_decision_id) == (None, None)
