"""Queries behind `GET /health`.

Two different tables can describe "the latest activity for a job kind": `ingest_runs` (every
scheduled or requested run the worker actually executed, with counts but no status/error
text) and `job_requests` (the request queue, with a real status/error but only for kinds
someone requested through the API/CLI). `_job_statuses` merges them per kind, picking
whichever of the two has the more recent timestamp, and synthesizes a status/error pair for
an `ingest_runs`-only kind from its `errors` count and `notes`.
"""

from collections.abc import Sequence
from datetime import datetime, time, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signals.api.queries.common import now, sec_url
from signals.api.schemas import BackfillStep, Coverage, HealthOut, JobStatusOut, ParseErrorOut
from signals.db.models import (
    Decision,
    DecisionReturn,
    Filing,
    FundPositionChange,
    IngestRun,
    InsiderTransaction,
    Issuer,
    JobRequest,
    Security,
)
from signals.domain.appstate import get_state
from signals.domain.calendars import is_sec_business_day


# --------------------------------------------------------------------------- jobs
def _job_statuses(session: Session) -> list[JobStatusOut]:
    ingest_by_job: dict[str, IngestRun] = {}
    for row in session.execute(
        select(IngestRun).order_by(IngestRun.job, IngestRun.started_at)
    ).scalars():
        ingest_by_job[row.job] = row  # ascending order: the last write per key is the latest
    request_by_kind: dict[str, JobRequest] = {}
    for row in session.execute(
        select(JobRequest).order_by(JobRequest.kind, JobRequest.requested_at)
    ).scalars():
        request_by_kind[row.kind] = row

    out = []
    for kind in sorted(set(ingest_by_job) | set(request_by_kind)):
        ingest = ingest_by_job.get(kind)
        req = request_by_kind.get(kind)
        use_request = req is not None and (
            ingest is None or (req.started_at or req.requested_at) >= ingest.started_at
        )
        if use_request and req is not None:
            out.append(
                JobStatusOut(
                    kind=kind,
                    last_started_at=req.started_at,
                    last_finished_at=req.finished_at,
                    last_status=req.status,
                    last_error=req.error,
                )
            )
        elif ingest is not None:
            status = "error" if ingest.errors > 0 else "ok"
            out.append(
                JobStatusOut(
                    kind=kind,
                    last_started_at=ingest.started_at,
                    last_finished_at=ingest.finished_at,
                    last_status=status,
                    last_error=(ingest.notes or {}).get("error"),
                )
            )
    return out


# --------------------------------------------------------------------------- feed delay
def _percentile(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    k = (len(values) - 1) * p
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] * (c - k) + values[c] * (k - f)


def _feed_delay(
    session: Session, as_of: datetime
) -> tuple[float | None, float | None, datetime | None]:
    cutoff = as_of - timedelta(hours=24)
    rows = session.execute(
        select(Filing.first_seen_at, Filing.accepted_at).where(
            Filing.source == "feed",
            Filing.first_seen_at.isnot(None),
            Filing.first_seen_at >= cutoff,
        )
    ).all()
    delays = sorted(
        (r.first_seen_at - r.accepted_at).total_seconds() for r in rows if r.accepted_at is not None
    )
    last_seen = max((r.first_seen_at for r in rows), default=None)
    return _percentile(delays, 0.50), _percentile(delays, 0.95), last_seen


# --------------------------------------------------------------------------- parse errors
def _parse_errors(session: Session) -> list[ParseErrorOut]:
    rows = session.execute(
        select(Filing)
        .where(Filing.parse_status == "error")
        .order_by(Filing.parsed_at.desc().nulls_last(), Filing.filed_date.desc())
        .limit(50)
    ).scalars()
    return [
        ParseErrorOut(
            accession_no=f.accession_no,
            form_type=f.form_type,
            filed_date=f.filed_date,
            error=f.parse_error or "",
            sec_url=sec_url(f.primary_cik, f.accession_no),
        )
        for f in rows
    ]


def _has_recent_parse_errors(session: Session, as_of: datetime) -> bool:
    cutoff = as_of - timedelta(hours=24)
    return (
        session.execute(
            select(Filing.accession_no)
            .where(
                Filing.parse_status == "error",
                Filing.parsed_at.isnot(None),
                Filing.parsed_at >= cutoff,
            )
            .limit(1)
        ).first()
        is not None
    )


# --------------------------------------------------------------------------- backfill
def _backfill_steps(session: Session) -> list[BackfillStep]:
    latest: dict[str, JobRequest] = {}
    for row in session.execute(
        select(JobRequest)
        .where(JobRequest.kind.like("backfill_%"))
        .order_by(JobRequest.kind, JobRequest.requested_at)
    ).scalars():
        latest[row.kind] = row  # ascending: last write per kind is the latest request

    out = []
    for kind in sorted(latest):
        row = latest[kind]
        progress = row.progress or {}
        done_units = (
            progress["done_units"]
            if "done_units" in progress
            else len(progress.get("datasets_done", []))
        )
        out.append(
            BackfillStep(
                step=kind,
                status=row.status,
                done_units=done_units,
                total_units=progress.get("total_units"),
                updated_at=row.finished_at or row.started_at or row.requested_at,
            )
        )
    return out


# --------------------------------------------------------------------------- coverage
def _issuers_with_sector_pct(session: Session) -> float | None:
    issuer_ciks = set(session.execute(select(InsiderTransaction.issuer_cik).distinct()).scalars())
    if not issuer_ciks:
        return None
    with_sector = session.execute(
        select(func.count())
        .select_from(Issuer)
        .where(Issuer.cik.in_(issuer_ciks), Issuer.sector.isnot(None))
    ).scalar_one()
    return with_sector / len(issuer_ciks)


def _cusip_value_mapped_pct(session: Session) -> float | None:
    latest_period = session.execute(
        select(func.max(FundPositionChange.period))
    ).scalar_one_or_none()
    if latest_period is None:
        return None
    changes = list(
        session.execute(
            select(FundPositionChange).where(FundPositionChange.period == latest_period)
        ).scalars()
    )
    total_value = sum(c.value_usd or 0.0 for c in changes)
    if not total_value:
        return None
    cusips = {c.cusip for c in changes}
    mapped = set(
        session.execute(
            select(Security.cusip).where(
                Security.cusip.in_(cusips), Security.issuer_cik.isnot(None)
            )
        ).scalars()
    )
    mapped_value = sum(c.value_usd or 0.0 for c in changes if c.cusip in mapped)
    return mapped_value / total_value


def _decisions_with_prices_pct(session: Session) -> float | None:
    total = session.execute(select(func.count()).select_from(Decision)).scalar_one()
    if not total:
        return None
    with_prices = session.execute(
        select(func.count(func.distinct(DecisionReturn.decision_id))).where(
            DecisionReturn.basis == "filed"
        )
    ).scalar_one()
    return with_prices / total


def _decisions_last_price_exit_pct(session: Session) -> float | None:
    rows = list(
        session.execute(
            select(DecisionReturn.exit_reason).where(
                DecisionReturn.basis == "filed", DecisionReturn.horizon == "6m"
            )
        ).scalars()
    )
    if not rows:
        return None
    return sum(1 for reason in rows if reason == "last_price") / len(rows)


def _coverage(session: Session) -> Coverage:
    return Coverage(
        issuers_with_sector_pct=_issuers_with_sector_pct(session),
        cusip_value_mapped_pct=_cusip_value_mapped_pct(session),
        decisions_with_prices_pct=_decisions_with_prices_pct(session),
        decisions_last_price_exit_pct=_decisions_last_price_exit_pct(session),
    )


# --------------------------------------------------------------------------- status
def _status(
    as_of: datetime,
    sec_blocked_until: datetime | None,
    live_poll_last_success: datetime | None,
    has_recent_parse_errors: bool,
) -> Literal["ok", "warn", "error"]:
    if sec_blocked_until is not None and sec_blocked_until > as_of:
        return "error"
    if live_poll_last_success is not None:
        stale = as_of - live_poll_last_success > timedelta(minutes=30)
        business_hours = is_sec_business_day(as_of.date()) and time(6, 0) <= as_of.time() <= time(
            22, 0
        )
        if stale and business_hours:
            return "error"
    if has_recent_parse_errors:
        return "warn"
    return "ok"


# --------------------------------------------------------------------------- assembly
def get_health(session: Session) -> HealthOut:
    as_of = now()
    p50, p95, last_seen = _feed_delay(session, as_of)

    blocked_raw = get_state(session, "sec_blocked_until")
    sec_blocked_until = datetime.fromisoformat(blocked_raw["until"]) if blocked_raw else None
    poll_raw = get_state(session, "live_poll_last_success")
    live_poll_last_success = datetime.fromisoformat(poll_raw["at"]) if poll_raw else None
    has_recent = _has_recent_parse_errors(session, as_of)

    return HealthOut(
        status=_status(as_of, sec_blocked_until, live_poll_last_success, has_recent),
        jobs=_job_statuses(session),
        feed_delay_p50_s=p50,
        feed_delay_p95_s=p95,
        last_filing_seen_at=last_seen,
        parse_errors=_parse_errors(session),
        backfill=_backfill_steps(session),
        coverage=_coverage(session),
        sec_blocked_until=sec_blocked_until,
    )
