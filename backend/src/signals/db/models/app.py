"""App and operations tables: users, watchlists, job requests, run log, small state."""

import datetime as dt

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from signals.db.base import Base, CreatedMixin, TimestampMixin


class User(CreatedMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class Watchlist(TimestampMixin, Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_watchlists_user_name"),)


class WatchlistItem(CreatedMixin, Base):
    __tablename__ = "watchlist_items"

    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(Text, primary_key=True)  # insider | company | fund
    cik: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    added_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JobRequest(CreatedMixin, Base):
    __tablename__ = "job_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="requested", nullable=False)
    progress: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_job_requests_status_requested", "status", "requested_at"),)


class IngestRun(CreatedMixin, Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    fetched: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    new_rows: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    missed: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    errors: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    notes: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), nullable=False)

    __table_args__ = (Index("ix_ingest_runs_job_started", "job", text("started_at DESC")),)


class AppState(Base):
    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
