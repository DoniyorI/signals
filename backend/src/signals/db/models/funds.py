"""13F managers, filings, per-filing positions and quarter-over-quarter changes."""

from datetime import date, datetime

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
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from signals.db.base import Base, TimestampMixin


class FundManager(TimestampMixin, Base):
    __tablename__ = "fund_managers"

    cik: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_tracked: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    tracked_reason: Mapped[str | None] = mapped_column(Text)
    latest_period: Mapped[date | None] = mapped_column(Date)
    latest_value_usd: Mapped[float | None] = mapped_column(Double)
    latest_positions: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        Index(
            "ix_fund_managers_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )


class FundFiling(TimestampMixin, Base):
    __tablename__ = "fund_filings"

    accession_no: Mapped[str] = mapped_column(
        ForeignKey("filings.accession_no", ondelete="CASCADE"), primary_key=True
    )
    filer_cik: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_of_report: Mapped[date] = mapped_column(Date, nullable=False)
    filed_date: Mapped[date] = mapped_column(Date, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submission_type: Mapped[str | None] = mapped_column(Text)
    report_type: Mapped[str | None] = mapped_column(Text)
    amendment_type: Mapped[str | None] = mapped_column(Text)  # RESTATEMENT | NEW HOLDINGS
    amendment_no: Mapped[int | None] = mapped_column(Integer)
    value_total_usd: Mapped[float | None] = mapped_column(Double)
    entry_total: Mapped[int | None] = mapped_column(Integer)
    superseded: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)

    __table_args__ = (Index("ix_fund_filings_filer_period", "filer_cik", "period_of_report"),)


class FundPosition(Base):
    """One row per filing and CUSIP. Range-partitioned by period (one partition a year).
    No timestamps: this is the largest table and rows are replaced, never edited."""

    __tablename__ = "fund_positions"

    period: Mapped[date] = mapped_column(Date, primary_key=True)
    accession_no: Mapped[str] = mapped_column(Text, primary_key=True)
    cusip: Mapped[str] = mapped_column(Text, primary_key=True)
    put_call: Mapped[str] = mapped_column(Text, primary_key=True, server_default="")
    filer_cik: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name_of_issuer: Mapped[str | None] = mapped_column(Text)
    title_of_class: Mapped[str | None] = mapped_column(Text)
    shares: Mapped[float | None] = mapped_column(Double)
    sh_prn: Mapped[str | None] = mapped_column(Text)
    value_usd: Mapped[float | None] = mapped_column(Double)
    is_effective: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)

    __table_args__ = (
        Index("ix_fund_positions_filer_period", "filer_cik", "period"),
        Index("ix_fund_positions_cusip_period", "cusip", "period"),
        {"postgresql_partition_by": "RANGE (period)"},
    )


class FundPositionChange(Base):
    __tablename__ = "fund_position_changes"

    filer_cik: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    period: Mapped[date] = mapped_column(Date, primary_key=True)
    cusip: Mapped[str] = mapped_column(Text, primary_key=True)
    put_call: Mapped[str] = mapped_column(Text, primary_key=True, server_default="")
    prev_shares: Mapped[float | None] = mapped_column(Double)
    shares: Mapped[float | None] = mapped_column(Double)
    change: Mapped[str] = mapped_column(Text, nullable=False)
    shares_change_pct: Mapped[float | None] = mapped_column(Double)
    value_usd: Mapped[float | None] = mapped_column(Double)
    weight: Mapped[float | None] = mapped_column(Double)
    prev_weight: Mapped[float | None] = mapped_column(Double)

    __table_args__ = (Index("ix_fund_changes_cusip_period", "cusip", "period"),)
