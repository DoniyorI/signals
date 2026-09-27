"""Tables rebuilt by analytics: decisions, returns, positions, profile stats, curves, feed."""

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from signals.db.base import Base, CreatedMixin, TimestampMixin


class Decision(TimestampMixin, Base):
    """An episode: one owner group's same-direction open-market trades in one issuer."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_group: Mapped[str] = mapped_column(Text, nullable=False)
    issuer_cik: Mapped[int] = mapped_column(BigInteger, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)  # buy | sell
    is_planned: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    plan_10b5_1: Mapped[str] = mapped_column(Text, server_default="none", nullable=False)
    first_trade_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    last_trade_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    shares: Mapped[float | None] = mapped_column(Double)
    value_usd: Mapped[float | None] = mapped_column(Double)
    vwap: Mapped[float | None] = mapped_column(Double)
    stake_change_pct: Mapped[float | None] = mapped_column(Double)
    is_new_position: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    sell_fraction: Mapped[float | None] = mapped_column(Double)
    first_accession: Mapped[str] = mapped_column(Text, nullable=False)
    accessions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), nullable=False
    )
    accepted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    filed_date: Mapped[dt.date | None] = mapped_column(Date)
    lag_days: Mapped[int | None] = mapped_column(Integer)
    lag_cost: Mapped[float | None] = mapped_column(Double)
    badges: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), nullable=False
    )

    __table_args__ = (
        Index("ix_decisions_issuer_date", "issuer_cik", "first_trade_date"),
        Index("ix_decisions_owner_group", "owner_group"),
    )


class DecisionOwner(CreatedMixin, Base):
    __tablename__ = "decision_owners"

    decision_id: Mapped[int] = mapped_column(
        ForeignKey("decisions.id", ondelete="CASCADE"), primary_key=True
    )
    owner_cik: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    __table_args__ = (Index("ix_decision_owners_owner_cik", "owner_cik"),)


class DecisionReturn(Base):
    __tablename__ = "decision_returns"

    decision_id: Mapped[int] = mapped_column(
        ForeignKey("decisions.id", ondelete="CASCADE"), primary_key=True
    )
    basis: Mapped[str] = mapped_column(Text, primary_key=True)  # filed | executed
    horizon: Mapped[str] = mapped_column(Text, primary_key=True)  # 1m | 3m | 6m | 12m
    entry_date: Mapped[dt.date | None] = mapped_column(Date)
    entry_price_adj: Mapped[float | None] = mapped_column(Double)
    entry_kind: Mapped[str | None] = mapped_column(Text)
    exit_date: Mapped[dt.date | None] = mapped_column(Date)
    raw_return: Mapped[float | None] = mapped_column(Double)
    excess_spy: Mapped[float | None] = mapped_column(Double)
    excess_qqq: Mapped[float | None] = mapped_column(Double)
    excess_sector: Mapped[float | None] = mapped_column(Double)
    is_complete: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    exit_reason: Mapped[str | None] = mapped_column(Text)
    flags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), nullable=False
    )


class Position(TimestampMixin, Base):
    """Latest reported non-derivative holding. security_title is '' when not reported."""

    __tablename__ = "positions"

    owner_cik: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    issuer_cik: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    security_title: Mapped[str] = mapped_column(Text, primary_key=True, server_default="")
    direct_indirect: Mapped[str] = mapped_column(Text, primary_key=True, server_default="")
    shares: Mapped[float | None] = mapped_column(Double)
    as_of_date: Mapped[dt.date | None] = mapped_column(Date)
    last_accession: Mapped[str | None] = mapped_column(Text)


class ProfileStats(TimestampMixin, Base):
    __tablename__ = "profile_stats"

    kind: Mapped[str] = mapped_column(Text, primary_key=True)  # insider | fund
    cik: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    basis: Mapped[str] = mapped_column(Text, primary_key=True)
    include_10b5_1: Mapped[bool] = mapped_column(Boolean, primary_key=True)
    n_decisions: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    n_buys: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    n_sells: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    n_complete: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    avg_roi_6m: Mapped[float | None] = mapped_column(Double)
    avg_roi_6m_raw: Mapped[float | None] = mapped_column(Double)
    median_6m: Mapped[float | None] = mapped_column(Double)
    hit_rate: Mapped[float | None] = mapped_column(Double)
    best_decision_id: Mapped[int | None] = mapped_column(BigInteger)
    worst_decision_id: Mapped[int | None] = mapped_column(BigInteger)
    avg_lag_days: Mapped[float | None] = mapped_column(Double)
    avg_lag_cost: Mapped[float | None] = mapped_column(Double)
    shrunk_mean: Mapped[float | None] = mapped_column(Double)
    rating: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[str | None] = mapped_column(Text)
    risk_label: Mapped[str | None] = mapped_column(Text)
    primary_issuer_cik: Mapped[int | None] = mapped_column(BigInteger)
    sector: Mapped[str | None] = mapped_column(Text)
    last_trade_date: Mapped[dt.date | None] = mapped_column(Date)


class ProfileWindow(TimestampMixin, Base):
    __tablename__ = "profile_windows"

    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    cik: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    basis: Mapped[str] = mapped_column(Text, primary_key=True)
    include_10b5_1: Mapped[bool] = mapped_column(Boolean, primary_key=True)
    window: Mapped[str] = mapped_column(Text, primary_key=True)  # ytd | 1y | 3y | 5y
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    end_date: Mapped[dt.date | None] = mapped_column(Date)
    ret: Mapped[float | None] = mapped_column(Double)
    ret_spy: Mapped[float | None] = mapped_column(Double)
    ret_qqq: Mapped[float | None] = mapped_column(Double)
    ret_sector: Mapped[float | None] = mapped_column(Double)
    annualized: Mapped[float | None] = mapped_column(Double)
    vol: Mapped[float | None] = mapped_column(Double)
    max_drawdown: Mapped[float | None] = mapped_column(Double)
    beta: Mapped[float | None] = mapped_column(Double)
    time_invested_pct: Mapped[float | None] = mapped_column(Double)


class FundNavDaily(Base):
    __tablename__ = "fund_nav_daily"

    cik: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    basis: Mapped[str] = mapped_column(Text, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    nav: Mapped[float] = mapped_column(Double, nullable=False)
    nav_spy: Mapped[float | None] = mapped_column(Double)
    nav_qqq: Mapped[float | None] = mapped_column(Double)
    nav_sector: Mapped[float | None] = mapped_column(Double)
    coverage: Mapped[float | None] = mapped_column(Double)


class FeedItem(TimestampMixin, Base):
    """One row per filing for fast feed queries. No FK to filings: rows are rebuilt by
    ingestion keyed on accession, and filings are never deleted."""

    __tablename__ = "feed_items"

    accession_no: Mapped[str] = mapped_column(Text, primary_key=True)
    accepted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    filed_date: Mapped[dt.date | None] = mapped_column(Date)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    issuer_cik: Mapped[int | None] = mapped_column(BigInteger)
    issuer_name: Mapped[str | None] = mapped_column(Text)
    ticker: Mapped[str | None] = mapped_column(Text)
    owner_group: Mapped[str | None] = mapped_column(Text)
    owner_ciks: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), server_default=text("'{}'"), nullable=False
    )
    owner_names: Mapped[str | None] = mapped_column(Text)
    top_role: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str | None] = mapped_column(Text)
    codes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), nullable=False
    )
    value_usd: Mapped[float | None] = mapped_column(Double)
    shares: Mapped[float | None] = mapped_column(Double)
    price: Mapped[float | None] = mapped_column(Double)
    plan_10b5_1: Mapped[str | None] = mapped_column(Text)
    badges: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), nullable=False
    )
    market_cap_usd: Mapped[float | None] = mapped_column(Double)
    sector: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, server_default="", nullable=False)
    lag_days: Mapped[int | None] = mapped_column(Integer)
    first_trade_date: Mapped[dt.date | None] = mapped_column(Date)

    __table_args__ = (
        Index("ix_feed_items_accepted_at", text("accepted_at DESC")),
        Index("ix_feed_items_issuer_accepted", "issuer_cik", "accepted_at"),
        Index("ix_feed_items_filed_date", "filed_date"),
    )
