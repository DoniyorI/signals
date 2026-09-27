"""Daily bars. Raw OHLC plus a split/dividend adjusted close (adj_factor = adj_close / close)."""

import datetime as dt

from sqlalchemy import Date, Double, Text
from sqlalchemy.orm import Mapped, mapped_column

from signals.db.base import Base


class PriceDaily(Base):
    __tablename__ = "prices_daily"

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Double)
    high: Mapped[float | None] = mapped_column(Double)
    low: Mapped[float | None] = mapped_column(Double)
    close: Mapped[float] = mapped_column(Double, nullable=False)
    volume: Mapped[float | None] = mapped_column(Double)
    adj_close: Mapped[float] = mapped_column(Double, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
