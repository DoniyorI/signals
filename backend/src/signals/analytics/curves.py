"""Performance curves served by the API (spec 9.4, 9.5): `analytics.types.Curve` values.

- Insider curves are computed on demand: the owner's copycat on that basis from the first
  entry to `as_of` (built exactly as `profile_windows` were), its windows, no coverage. They
  are cached in an LRU of 256 keyed by (cik, basis, include_10b5_1, as_of, the last
  analytics run), so a new run retires every cached curve.
- Fund curves read the stored `fund_nav_daily` rows up to `as_of` and the stored fund
  windows; `coverage_pct` is the latest row's priced-value coverage. Untracked funds raise
  LookupError.

`points` has the columns nav, spy, qqq and sector, each divided by its first value. A
benchmark without any price (no series loaded yet) is drawn flat at 1.0, since the API's
points are plain floats; its window numbers stay None.
"""

from dataclasses import replace
from datetime import date
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from signals.analytics.stats import insider_nav
from signals.analytics.types import Curve, WindowResult
from signals.analytics.windows import WINDOW_ORDER, empty_window, window_stats
from signals.db.models import FundManager, FundNavDaily, ProfileWindow
from signals.domain.appstate import get_state
from signals.domain.types import Basis, ProfileKind

ANALYTICS_VERSION_KEY = "analytics_version"  # app_state: {"as_of": ..., "run_at": ...}
POINT_COLUMNS = ("nav", "spy", "qqq", "sector")
CACHE_SIZE = 256

_CurveKey = tuple[int, str, bool, date, Any]


def _points(frame: pd.DataFrame) -> pd.DataFrame:
    index = pd.Index(list(frame.index), dtype=object)
    columns: dict[str, pd.Series] = {}
    for name in POINT_COLUMNS:
        raw = frame[name].to_numpy(dtype=float) if name in frame.columns else np.nan
        values = pd.Series(raw, index=index, dtype=float)
        known = values.dropna()
        if known.empty or known.iloc[0] == 0:
            columns[name] = pd.Series(1.0, index=index, dtype=float)
        else:
            columns[name] = (values / known.iloc[0]).ffill().fillna(1.0)
    return pd.DataFrame(columns, index=index)


@lru_cache(maxsize=CACHE_SIZE)
def _curve_slots(key: _CurveKey) -> dict[str, Curve]:
    """One memo slot per key; lru_cache bounds and evicts the slots."""
    return {}


def _insider_curve(
    session: Session, cik: int, basis: Basis, include_10b5_1: bool, as_of: date
) -> Curve:
    nav = insider_nav(session, cik, basis=basis, include_10b5_1=include_10b5_1, as_of=as_of)
    return Curve(
        basis=basis,
        points=_points(nav),
        windows=window_stats(nav, as_of),
        coverage_pct=None,
        as_of=as_of,
    )


def insider_curve(
    session: Session, cik: int, *, basis: str, include_10b5_1: bool, as_of: date
) -> Curve:
    version = get_state(session, ANALYTICS_VERSION_KEY) or {}
    kind = Basis(basis)
    slot = _curve_slots((int(cik), kind.value, bool(include_10b5_1), as_of, version.get("run_at")))
    curve = slot.get("curve")
    if curve is None:
        curve = _insider_curve(session, int(cik), kind, bool(include_10b5_1), as_of)
        slot["curve"] = curve
    return replace(curve, points=curve.points.copy())  # callers may reshape their copy


def _stored_windows(session: Session, cik: int, basis: Basis) -> list[WindowResult]:
    rows = session.scalars(
        select(ProfileWindow).where(
            ProfileWindow.kind == ProfileKind.FUND.value,
            ProfileWindow.cik == cik,
            ProfileWindow.basis == basis.value,
            ProfileWindow.include_10b5_1.is_(False),
        )
    )
    stored = {row.window: row for row in rows}
    windows: list[WindowResult] = []
    for window in WINDOW_ORDER:
        row = stored.get(window.value)
        if row is None:
            windows.append(empty_window(window))
            continue
        windows.append(
            WindowResult(
                window=window,
                start=row.start_date,
                end=row.end_date,
                ret=row.ret,
                ret_spy=row.ret_spy,
                ret_qqq=row.ret_qqq,
                ret_sector=row.ret_sector,
                annualized=row.annualized,
                vol=row.vol,
                max_drawdown=row.max_drawdown,
                beta=row.beta,
                time_invested_pct=row.time_invested_pct,
            )
        )
    return windows


def fund_curve(session: Session, cik: int, *, basis: str, as_of: date) -> Curve:
    if not session.scalar(select(FundManager.is_tracked).where(FundManager.cik == cik)):
        raise LookupError("fund not tracked")
    kind = Basis(basis)
    rows = session.execute(
        select(
            FundNavDaily.date,
            FundNavDaily.nav,
            FundNavDaily.nav_spy,
            FundNavDaily.nav_qqq,
            FundNavDaily.nav_sector,
            FundNavDaily.coverage,
        )
        .where(
            FundNavDaily.cik == cik,
            FundNavDaily.basis == kind.value,
            FundNavDaily.date <= as_of,
        )
        .order_by(FundNavDaily.date)
    ).all()
    frame = pd.DataFrame(
        {
            name: pd.Series([row[i] for row in rows], dtype=float)
            for i, name in enumerate(POINT_COLUMNS, start=1)
        }
    ).set_axis(pd.Index([row.date for row in rows], dtype=object))
    return Curve(
        basis=kind,
        points=_points(frame),
        windows=_stored_windows(session, cik, kind),
        coverage_pct=rows[-1].coverage if rows else None,
        as_of=as_of,
    )
