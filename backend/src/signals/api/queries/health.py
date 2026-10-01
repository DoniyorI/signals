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
    FeedItem,
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
from signals.jobs import BACKFILL_STEPS


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
            ingest is None
            or (req.finished_at or req.started_at or req.requested_at)
            >= (ingest.finished_at or ingest.started_at)
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
            status = (
                "running" if ingest.finished_at is None else "error" if ingest.errors > 0 else "ok"
            )
            out.append(
                JobStatusOut(
                    kind=kind,
                    last_started_at=ingest.started_at,
                    last_finished_at=ingest.finished_at,
                    last_status=status,
                    last_error=(ingest.notes or {}).get("error")
                    or (ingest.notes or {}).get("exception"),
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
            Filing.parse_status == "parsed",
            select(FeedItem.accession_no)
            .where(FeedItem.accession_no == Filing.accession_no)
            .exists(),
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
        .where(JobRequest.kind.like("backfill_%") | JobRequest.kind.in_(BACKFILL_STEPS))
        .order_by(JobRequest.kind, JobRequest.requested_at, JobRequest.id)
    ).scalars():
        latest[row.kind] = row  # ascending: last write per kind is the latest request

    # Parent and standalone requests both describe real steps; prefer the latest run.
    candidates: dict[str, tuple[JobRequest, dict, str, datetime | None]] = {}
    for kind, row in latest.items():
        progress = row.progress or {}
        if kind != "backfill_all":
            candidates[kind] = (row, progress, row.status, _checkpoint_time(progress, row))
    parent = latest.get("backfill_all")
    if parent is not None:
        progress = parent.progress or {}
        done = set(progress.get("done_steps", []))
        active = next((kind for kind in BACKFILL_STEPS if kind not in done), None)
        for kind in BACKFILL_STEPS:
            standalone = candidates.get(kind)
            if standalone is not None and (standalone[0].requested_at, standalone[0].id) > (
                parent.requested_at,
                parent.id,
            ):
                continue
            sub = progress.get("steps", {}).get(kind, {})
            status = (
                "done"
                if kind in done or parent.status == "done"
                else (
                    parent.status if kind == active and parent.status != "requested" else "pending"
                )
            )
            timestamp_progress = sub or (progress if kind == active else {})
            if kind == active and "updated_at" not in sub:
                timestamp_progress = {**sub, "updated_at": progress.get("updated_at")}
            candidates[kind] = (parent, sub, status, _checkpoint_time(timestamp_progress, parent))

    out: list[BackfillStep] = []
    for kind, (row, progress, status, updated_at) in sorted(candidates.items()):
        units, total = _progress_units(progress, status)
        out.append(
            BackfillStep(
                step=kind, status=status, done_units=units, total_units=total, updated_at=updated_at
            )
        )
        # Keep heterogeneous units separate: ZIP counts never mix with filing offsets.
        for name, gap in sorted(progress.items()):
            if not name.startswith("gap_fill_") or not isinstance(gap, dict):
                continue
            current = gap.get("current", {})
            # One completed quarter does not imply the whole gap step finished.
            gap_status = "done" if name in progress.get("result", {}) else status
            out.append(
                BackfillStep(
                    step=f"{kind}.{name}",
                    status=gap_status,
                    done_units=current.get("offset", 0),
                    total_units=None,
                    updated_at=_checkpoint_time(gap, row) if gap.get("updated_at") else updated_at,
                )
            )
    return out


def _checkpoint_time(progress: dict, row: JobRequest) -> datetime | None:
    stamp = progress.get("updated_at")
    if isinstance(stamp, str):
        try:
            return datetime.fromisoformat(stamp)
        except ValueError:
            pass
    return row.finished_at or row.started_at or row.requested_at


def _progress_units(progress: dict, status: str) -> tuple[int, int | None]:
    if "done_units" in progress:
        return progress["done_units"], progress.get("total_units")
    for key in ("datasets_done", "done"):
        if isinstance(progress.get(key), list):
            return len(progress[key]), progress.get("total_units")
    if "step" in progress:
        stages = (
            "positions",
            "decisions",
            "returns",
            "badges",
            "insider_stats",
            "funds",
            "feed",
            "version",
        )
        stage = progress["step"]
        if stage in stages:
            return len(stages) if status == "done" else stages.index(stage), len(stages)
    # Price jobs currently return their counters rather than checkpoint each symbol.
    result = progress.get("result", {})
    if isinstance(result.get("loaded"), int):
        return result["loaded"], result.get("requested")
    return 0, progress.get("total_units")


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
    has_job_errors: bool = False,
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
    if has_recent_parse_errors or has_job_errors:
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
    jobs = _job_statuses(session)

    return HealthOut(
        status=_status(
            as_of,
            sec_blocked_until,
            live_poll_last_success,
            has_recent,
            any(job.last_status in ("error", "failed") for job in jobs),
        ),
        jobs=jobs,
        feed_delay_p50_s=p50,
        feed_delay_p95_s=p95,
        last_filing_seen_at=last_seen,
        parse_errors=_parse_errors(session),
        backfill=_backfill_steps(session),
        coverage=_coverage(session),
        sec_blocked_until=sec_blocked_until,
    )
