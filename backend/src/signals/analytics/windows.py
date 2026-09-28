"""Window returns and risk over a copycat NAV frame (spec 9.4).

YTD runs from the previous year's last close; 1y/3y/5y are the trailing 252/756/1260
trading days (3y and 5y also annualized). A window longer than the history is empty
(every number None). Volatility is the annualized sample standard deviation of daily NAV
returns; beta is against SPY; time invested is the share of days with open lots.
"""

import bisect
import math
from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

from signals.analytics.types import WindowResult
from signals.domain.types import WINDOW_TRADING_DAYS, RiskLabel, Window

WINDOW_ORDER: tuple[Window, ...] = (Window.YTD, Window.Y1, Window.Y3, Window.Y5)
ANNUALIZED: frozenset[Window] = frozenset({Window.Y3, Window.Y5})
TRADING_DAYS_PER_YEAR = 252
RISK_LOW_BELOW = 0.20
RISK_HIGH_ABOVE = 0.40


def _finite(value: float) -> float | None:
    return float(value) if value is not None and math.isfinite(value) else None


def beta_of(
    returns: Sequence[float] | np.ndarray | pd.Series,
    bench: Sequence[float] | np.ndarray | pd.Series,
) -> float | None:
    """cov(r, r_bench) / var(r_bench) over days where both are known."""
    r = np.asarray(returns, dtype=float)
    b = np.asarray(bench, dtype=float)
    known = np.isfinite(r) & np.isfinite(b)
    r, b = r[known], b[known]
    if len(r) < 2:
        return None
    variance = float(np.var(b, ddof=1))
    if variance <= 0:
        return None
    return _finite(float(np.cov(r, b, ddof=1)[0, 1]) / variance)


def risk_label(vol: float | None) -> RiskLabel | None:
    if vol is None:
        return None
    if vol < RISK_LOW_BELOW:
        return RiskLabel.LOW
    if vol <= RISK_HIGH_ABOVE:
        return RiskLabel.MEDIUM
    return RiskLabel.HIGH


def empty_window(window: Window) -> WindowResult:
    return WindowResult(window, None, None, None, None, None, None, None, None, None, None, None)


def _column_return(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    values = frame[column].to_numpy(dtype=float)
    return _finite(values[-1] / values[0] - 1)


def _window(frame: pd.DataFrame, window: Window) -> WindowResult:
    nav = frame["nav"].to_numpy(dtype=float)
    daily = nav[1:] / nav[:-1] - 1
    n = len(daily)
    ret = _finite(nav[-1] / nav[0] - 1)
    vol = (
        _finite(float(np.std(daily, ddof=1)) * math.sqrt(TRADING_DAYS_PER_YEAR)) if n >= 2 else None
    )
    drawdown = _finite(float(np.min(nav / np.maximum.accumulate(nav) - 1)))
    beta = None
    if "spy" in frame.columns and n >= 2:
        spy = frame["spy"].to_numpy(dtype=float)
        beta = beta_of(daily, spy[1:] / spy[:-1] - 1)
    invested = None
    if "invested" in frame.columns:
        invested = float(np.mean(frame["invested"].to_numpy(dtype=float) > 0))
    annualized = None
    if window in ANNUALIZED and ret is not None and n > 0 and ret > -1:
        annualized = (1 + ret) ** (TRADING_DAYS_PER_YEAR / n) - 1
    return WindowResult(
        window=window,
        start=frame.index[0],
        end=frame.index[-1],
        ret=ret,
        ret_spy=_column_return(frame, "spy"),
        ret_qqq=_column_return(frame, "qqq"),
        ret_sector=_column_return(frame, "sector"),
        annualized=annualized,
        vol=vol,
        max_drawdown=drawdown,
        beta=beta,
        time_invested_pct=invested,
    )


def window_stats(nav: pd.DataFrame, as_of: date) -> list[WindowResult]:
    """Always 4 results, in the order ytd, 1y, 3y, 5y. `nav` is indexed by date with a `nav`
    column and optionally spy, qqq, sector and invested."""
    dates: list[date] = [d for d in nav.index if d <= as_of]
    frame = nav.iloc[: len(dates)] if dates else nav.iloc[:0]
    results: list[WindowResult] = []
    for window in WINDOW_ORDER:
        if not dates:
            results.append(empty_window(window))
            continue
        end = len(dates) - 1
        if window is Window.YTD:
            start = bisect.bisect_right(dates, date(as_of.year - 1, 12, 31)) - 1
        else:
            start = end - WINDOW_TRADING_DAYS[window]
        if start < 0:
            results.append(empty_window(window))
            continue
        results.append(_window(frame.iloc[start : end + 1], window))
    return results
