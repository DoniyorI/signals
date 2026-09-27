"""People (reporting owners), their roles, and one row per SEC filing."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Text,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from signals.db.base import Base, TimestampMixin


class Owner(TimestampMixin, Base):
    __tablename__ = "owners"

    cik: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    owner_type: Mapped[str] = mapped_column(Text, nullable=False)  # 'person' | 'entity'

    __table_args__ = (
        Index(
            "ix_owners_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )


class OwnerRole(TimestampMixin, Base):
    __tablename__ = "owner_roles"

    owner_cik: Mapped[int] = mapped_column(
        ForeignKey("owners.cik", ondelete="CASCADE"), primary_key=True
    )
    issuer_cik: Mapped[int] = mapped_column(
        ForeignKey("issuers.cik", ondelete="CASCADE"), primary_key=True
    )
    is_director: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    is_officer: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    officer_title: Mapped[str | None] = mapped_column(Text)
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), nullable=False
    )
    is_ten_pct_owner: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    is_other: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    other_text: Mapped[str | None] = mapped_column(Text)
    first_filed: Mapped[date | None] = mapped_column(Date)
    last_filed: Mapped[date | None] = mapped_column(Date)


class Filing(TimestampMixin, Base):
    """One EDGAR submission. `issuer_cik` has no FK: it is set from the SGML header
    before the handler creates the issuer row."""

    __tablename__ = "filings"

    accession_no: Mapped[str] = mapped_column(Text, primary_key=True)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    issuer_cik: Mapped[int | None] = mapped_column(BigInteger)
    primary_cik: Mapped[int] = mapped_column(BigInteger, nullable=False)
    filed_date: Mapped[date] = mapped_column(Date, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at_source: Mapped[str | None] = mapped_column(Text)  # sgml|submissions|missing
    period_of_report: Mapped[date | None] = mapped_column(Date)
    is_amendment: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    amends_accession: Mapped[str | None] = mapped_column(Text)
    original_filed_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    raw_path: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(Text, server_default="pending", nullable=False)
    parse_error: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_filings_form_type_filed_date", "form_type", "filed_date"),
        Index("ix_filings_issuer_cik", "issuer_cik"),
        Index(
            "ix_filings_parse_status_open",
            "parse_status",
            postgresql_where=text("parse_status <> 'parsed'"),
        ),
    )


class FilingOwner(TimestampMixin, Base):
    __tablename__ = "filing_owners"

    accession_no: Mapped[str] = mapped_column(
        ForeignKey("filings.accession_no", ondelete="CASCADE"), primary_key=True
    )
    owner_cik: Mapped[int] = mapped_column(
        ForeignKey("owners.cik", ondelete="CASCADE"), primary_key=True
    )
    is_director: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    is_officer: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    officer_title: Mapped[str | None] = mapped_column(Text)
    is_ten_pct_owner: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    is_other: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)

    __table_args__ = (Index("ix_filing_owners_owner_cik", "owner_cik"),)
