"""Insider activity: Form 3/4/5 rows, Form 144 notices, Schedule 13D/13G stakes."""

from datetime import date

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from signals.db.base import Base, TimestampMixin


class InsiderTransaction(TimestampMixin, Base):
    __tablename__ = "insider_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    accession_no: Mapped[str] = mapped_column(
        ForeignKey("filings.accession_no", ondelete="CASCADE"), nullable=False
    )
    table_kind: Mapped[str] = mapped_column(Text, nullable=False)  # nonderiv | deriv
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    issuer_cik: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner_group: Mapped[str] = mapped_column(Text, nullable=False)
    security_title: Mapped[str | None] = mapped_column(Text)
    transaction_date: Mapped[date | None] = mapped_column(Date)
    deemed_execution_date: Mapped[date | None] = mapped_column(Date)
    code: Mapped[str | None] = mapped_column(Text)
    form_type: Mapped[str | None] = mapped_column(Text)
    equity_swap: Mapped[bool | None] = mapped_column(Boolean)
    timeliness: Mapped[str | None] = mapped_column(Text)
    shares: Mapped[float | None] = mapped_column(Double)
    price: Mapped[float | None] = mapped_column(Double)
    value_usd: Mapped[float | None] = mapped_column(Double)
    acquired_disposed: Mapped[str | None] = mapped_column(Text)
    shares_owned_after: Mapped[float | None] = mapped_column(Double)
    value_owned_after: Mapped[float | None] = mapped_column(Double)
    direct_indirect: Mapped[str | None] = mapped_column(Text)
    nature_of_ownership: Mapped[str | None] = mapped_column(Text)
    plan_10b5_1: Mapped[str] = mapped_column(Text, server_default="none", nullable=False)
    exercise_price: Mapped[float | None] = mapped_column(Double)
    exercise_date: Mapped[date | None] = mapped_column(Date)
    expiration_date: Mapped[date | None] = mapped_column(Date)
    underlying_title: Mapped[str | None] = mapped_column(Text)
    underlying_shares: Mapped[float | None] = mapped_column(Double)
    footnotes: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), nullable=False)
    field_footnotes: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'"), nullable=False
    )
    superseded_by: Mapped[str | None] = mapped_column(Text)
    flags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("accession_no", "table_kind", "row_no", name="uq_insider_tx_row"),
        Index("ix_insider_tx_issuer_date", "issuer_cik", "transaction_date"),
        Index("ix_insider_tx_owner_group", "owner_group"),
        Index("ix_insider_tx_code_date", "code", "transaction_date"),
    )


class InsiderHolding(TimestampMixin, Base):
    __tablename__ = "insider_holdings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    accession_no: Mapped[str] = mapped_column(
        ForeignKey("filings.accession_no", ondelete="CASCADE"), nullable=False
    )
    table_kind: Mapped[str] = mapped_column(Text, nullable=False)
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    issuer_cik: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner_group: Mapped[str] = mapped_column(Text, nullable=False)
    security_title: Mapped[str | None] = mapped_column(Text)
    shares_owned: Mapped[float | None] = mapped_column(Double)
    value_owned: Mapped[float | None] = mapped_column(Double)
    direct_indirect: Mapped[str | None] = mapped_column(Text)
    nature_of_ownership: Mapped[str | None] = mapped_column(Text)
    exercise_price: Mapped[float | None] = mapped_column(Double)
    exercise_date: Mapped[date | None] = mapped_column(Date)
    expiration_date: Mapped[date | None] = mapped_column(Date)
    underlying_title: Mapped[str | None] = mapped_column(Text)
    underlying_shares: Mapped[float | None] = mapped_column(Double)
    footnotes: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), nullable=False)
    superseded_by: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("accession_no", "table_kind", "row_no", name="uq_insider_holding_row"),
        Index("ix_insider_holdings_owner_group", "owner_group"),
    )


class Form144Notice(TimestampMixin, Base):
    __tablename__ = "form144_notices"

    accession_no: Mapped[str] = mapped_column(
        ForeignKey("filings.accession_no", ondelete="CASCADE"), primary_key=True
    )
    filer_cik: Mapped[int | None] = mapped_column(BigInteger)
    issuer_cik: Mapped[int | None] = mapped_column(BigInteger)
    seller_name: Mapped[str | None] = mapped_column(Text)
    relationship: Mapped[str | None] = mapped_column(Text)
    security_class: Mapped[str | None] = mapped_column(Text)
    broker: Mapped[str | None] = mapped_column(Text)
    shares_to_sell: Mapped[float | None] = mapped_column(Double)
    market_value_usd: Mapped[float | None] = mapped_column(Double)
    shares_outstanding: Mapped[float | None] = mapped_column(Double)
    approx_sale_date: Mapped[date | None] = mapped_column(Date)
    exchange: Mapped[str | None] = mapped_column(Text)
    acquired_how: Mapped[str | None] = mapped_column(Text)
    acquired_date: Mapped[date | None] = mapped_column(Date)
    plan_10b5_1_adopted: Mapped[date | None] = mapped_column(Date)
    matched_sale_accession: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_form144_issuer_cik", "issuer_cik"),
        Index("ix_form144_filer_cik", "filer_cik"),
    )


class OwnershipStake(TimestampMixin, Base):
    """Schedule 13D (activist) or 13G (passive) 5%+ beneficial ownership report."""

    __tablename__ = "ownership_stakes"

    accession_no: Mapped[str] = mapped_column(
        ForeignKey("filings.accession_no", ondelete="CASCADE"), primary_key=True
    )
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    issuer_cik: Mapped[int | None] = mapped_column(BigInteger)
    cusip: Mapped[str | None] = mapped_column(Text)
    event_date: Mapped[date | None] = mapped_column(Date)
    amendment_no: Mapped[int | None] = mapped_column(Integer)
    is_activist: Mapped[bool] = mapped_column(Boolean, nullable=False)
    percent_of_class: Mapped[float | None] = mapped_column(Double)  # fraction
    shares: Mapped[float | None] = mapped_column(Double)
    reporting_persons: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'"), nullable=False
    )
    group_key: Mapped[str | None] = mapped_column(Text)
    purpose_excerpt: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)

    __table_args__ = (
        Index("ix_stakes_issuer_cik", "issuer_cik"),
        Index("ix_stakes_group_issuer", "group_key", "issuer_cik"),
    )
