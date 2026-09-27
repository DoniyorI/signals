"""Reference data: companies, dated tickers, 13F securities, SEC acceptance times."""

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
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from signals.db.base import Base, CreatedMixin, TimestampMixin


class Issuer(TimestampMixin, Base):
    __tablename__ = "issuers"

    cik: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sic: Mapped[int | None] = mapped_column(Integer)
    sic_description: Mapped[str | None] = mapped_column(Text)
    sector: Mapped[str | None] = mapped_column(Text)
    exchange: Mapped[str | None] = mapped_column(Text)
    state_of_inc: Mapped[str | None] = mapped_column(Text)
    fiscal_year_end: Mapped[str | None] = mapped_column(Text)
    shares_outstanding: Mapped[float | None] = mapped_column(Double)
    shares_outstanding_as_of: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)

    __table_args__ = (
        Index(
            "ix_issuers_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )


class Ticker(TimestampMixin, Base):
    """A symbol an issuer used over a date range (tickers change and get reused)."""

    __tablename__ = "tickers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    issuer_cik: Mapped[int] = mapped_column(
        ForeignKey("issuers.cik", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "issuer_cik", "symbol", "valid_from", name="uq_tickers_issuer_symbol_from"
        ),
        Index("ix_tickers_symbol", "symbol"),
    )


class TickerEvidence(TimestampMixin, Base):
    """Every sighting of a symbol for an issuer; `tickers` is rebuilt from this."""

    __tablename__ = "ticker_evidence"

    issuer_cik: Mapped[int] = mapped_column(
        ForeignKey("issuers.cik", ondelete="CASCADE"), primary_key=True
    )
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    min_seen: Mapped[date] = mapped_column(Date, nullable=False)
    max_seen: Mapped[date] = mapped_column(Date, nullable=False)
    sources: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), nullable=False
    )


class Security(TimestampMixin, Base):
    """A 13F security (CUSIP) mapped, when possible, to an issuer and ticker."""

    __tablename__ = "securities"

    cusip: Mapped[str] = mapped_column(Text, primary_key=True)
    issuer_cik: Mapped[int | None] = mapped_column(BigInteger)
    ticker: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    title_of_class: Mapped[str | None] = mapped_column(Text)
    figi: Mapped[str | None] = mapped_column(Text)
    security_type: Mapped[str | None] = mapped_column(Text)
    map_source: Mapped[str | None] = mapped_column(Text)
    map_status: Mapped[str] = mapped_column(Text, server_default="pending", nullable=False)

    __table_args__ = (
        Index("ix_securities_issuer_cik", "issuer_cik"),
        Index("ix_securities_ticker", "ticker"),
    )


class FilingAcceptance(CreatedMixin, Base):
    """SEC acceptance timestamps from submissions.zip, used for bulk-loaded filings."""

    __tablename__ = "filing_acceptance"

    accession_no: Mapped[str] = mapped_column(Text, primary_key=True)
    cik: Mapped[int | None] = mapped_column(BigInteger)
    form_type: Mapped[str | None] = mapped_column(Text)
    filing_date: Mapped[date | None] = mapped_column(Date)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
