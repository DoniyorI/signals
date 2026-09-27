"""Price provider protocol and read access to stored daily bars."""

from collections.abc import Sequence
from datetime import date
from typing import Protocol

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from signals.db.models import PriceDaily

BAR_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume", "adj_close", "source")


class PriceProvider(Protocol):
    name: str

    def daily_bars(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        """Columns: BAR_COLUMNS without `source`, one row per symbol and trading day."""
        ...


def get_bars(session: Session, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
    rows = session.execute(
        select(*(getattr(PriceDaily, c) for c in BAR_COLUMNS))
        .where(
            PriceDaily.symbol.in_(list(symbols)),
            PriceDaily.date >= start,
            PriceDaily.date <= end,
        )
        .order_by(PriceDaily.symbol, PriceDaily.date)
    ).all()
    return pd.DataFrame([tuple(r) for r in rows], columns=list(BAR_COLUMNS))
