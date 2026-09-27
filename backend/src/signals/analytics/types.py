"""Result types shared by analytics (producer) and the API (consumer)."""

from dataclasses import dataclass
from datetime import date

import pandas as pd

from signals.domain.types import Basis, Window


@dataclass(frozen=True)
class WindowResult:
    window: Window
    start: date | None
    end: date | None
    ret: float | None
    ret_spy: float | None
    ret_qqq: float | None
    ret_sector: float | None
    annualized: float | None
    vol: float | None
    max_drawdown: float | None
    beta: float | None
    time_invested_pct: float | None


@dataclass(frozen=True)
class Curve:
    """`points`: index = dates; columns nav, spy, qqq, sector, each 1.0 on the first row."""

    basis: Basis
    points: pd.DataFrame
    windows: list[WindowResult]
    coverage_pct: float | None
    as_of: date
