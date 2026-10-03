"""Verified SEC index membership, independent of locally ingested filings."""

from datetime import date

from sqlalchemy import Date, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from signals.db.base import Base


class CompletenessIndexMember(Base):
    __tablename__ = "completeness_index_members"

    accession_no: Mapped[str] = mapped_column(Text, primary_key=True)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    filed_date: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (Index("ix_completeness_index_members_date_form", "filed_date", "form_type"),)
