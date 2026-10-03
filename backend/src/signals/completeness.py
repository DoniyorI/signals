"""Worker-owned SEC baselines, retry accounting and database-only coverage reports.

Daily aggregate counts keep baselines small and let API readers apply configured family
start dates without reading archives or making HTTP requests. Missing baselines stay unknown.
"""

from collections import defaultdict
from datetime import date, timedelta
from typing import cast

import psycopg
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from signals.api.schemas import (
    CompletenessOut,
    FormFamily,
    FundCoverageOut,
    FundQuarterCoverageOut,
    PriceCoverageOut,
    QuarterCompletenessOut,
    ReturnCoverageOut,
    ReturnsCoverageOut,
    UnavailableAccessionOut,
    YearTransactionsOut,
)
from signals.config import Settings, get_settings
from signals.db.models import (
    AppState,
    CompletenessIndexMember,
    Decision,
    DecisionReturn,
    Filing,
    FundFiling,
    FundManager,
    IngestRun,
    InsiderTransaction,
    JobRequest,
    PriceDaily,
)
from signals.db.session import session_scope
from signals.domain.appstate import get_state, set_state
from signals.domain.calendars import (
    ET,
    add_trading_days,
    now_et,
    prev_trading_day,
    session_open_close,
)
from signals.domain.types import FORM144_FORMS, FUND_FORMS, INSIDER_FORMS, STAKE_FORMS
from signals.ingest.indexes import IndexEntry, full_index_url, parse_form_idx
from signals.jobs import JobContext, register_job, request_job
from signals.prices.universe import build_price_universe
from signals.sec.archive import RawArchive
from signals.sec.client import SecBlockedError, SecClient

CompletenessReport = CompletenessOut
FAMILIES: dict[FormFamily, frozenset[str]] = {
    "ownership": INSIDER_FORMS,
    "form144": FORM144_FORMS,
    "stakes": STAKE_FORMS,
    "13f": FUND_FORMS,
}
INDEX_PREFIX = "completeness_index:"
ATTEMPT_PREFIX = "completeness_attempt:"
MEMBERSHIP_VERSION = 1
TARGET = 0.995


def quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    if quarter not in (1, 2, 3, 4):
        raise ValueError("quarter must be 1 through 4")
    start = date(year, (quarter - 1) * 3 + 1, 1)
    following = date(year + 1, 1, 1) if quarter == 4 else date(year, quarter * 3 + 1, 1)
    return start, following - timedelta(days=1)


def quarter_of(day: date) -> tuple[int, int]:
    return day.year, (day.month - 1) // 3 + 1


def quarters_between(start: date, end: date):
    year, quarter = quarter_of(start)
    while (year, quarter) <= quarter_of(end):
        yield year, quarter
        quarter = quarter + 1 if quarter < 4 else 1
        if quarter == 1:
            year += 1


def family_starts(settings: Settings) -> dict[FormFamily, date]:
    return {
        "ownership": settings.backfill_start,
        "form144": max(settings.backfill_start, settings.form144_start),
        "stakes": max(settings.backfill_start, settings.stakes_start),
        "13f": settings.backfill_start,
    }


def family_for(form_type: str) -> FormFamily | None:
    return next((family for family, forms in FAMILIES.items() if form_type in forms), None)


def _index_entries(body: bytes) -> list[IndexEntry]:
    decoded = body.decode("utf-8", errors="replace")
    if "Form Type" not in decoded or not any(
        line.startswith("---") for line in decoded.splitlines()
    ):
        raise ValueError("Invalid SEC form index header")
    entries = parse_form_idx(decoded)
    lines = decoded.splitlines()
    delimiter = next(i for i, line in enumerate(lines) if line.startswith("---"))
    if len(entries) != sum(bool(line.strip()) for line in lines[delimiter + 1 :]):
        raise ValueError("Invalid SEC form index data row")
    return entries


def index_counts(
    session: Session,
    sec: SecClient,
    archive: RawArchive,
    year: int,
    quarter: int,
    *,
    as_of: date | None = None,
    settings: Settings | None = None,
) -> dict[str, int]:
    """Fetch/archive a full index and persist unique accession counts by filing date.

    Returned counts include every family regardless of its supported parser era; the
    report applies family scope to both sides. The current quarter always excludes today.
    """
    start, end = quarter_bounds(year, quarter)
    as_of = as_of or now_et().date()
    key = f"{year}Q{quarter}"
    body = sec.get(full_index_url(year, quarter))
    archive.put("full_index", key, body, "idx")
    entries = _index_entries(body)
    if not entries and (year, quarter) < quarter_of(as_of):
        raise ValueError("Empty SEC form index for a closed quarter")
    through = min(end, as_of - timedelta(days=1))
    counts: dict[str, int] = dict.fromkeys(FAMILIES, 0)
    daily: dict[str, dict[str, int]] = {}
    seen: set[str] = set()
    members: list[IndexEntry] = []
    for entry in entries:
        family = family_for(entry.form_type)
        if family is None or not start <= entry.date_filed <= through or entry.accession_no in seen:
            continue
        seen.add(entry.accession_no)
        members.append(entry)
        counts[family] += 1
        day = daily.setdefault(entry.date_filed.isoformat(), dict.fromkeys(FAMILIES, 0))
        day[family] += 1
    # An in-progress full index can lag the daily feed. Preserve its observed frontier.
    if quarter_of(as_of) == (year, quarter):
        through = max(
            (e.date_filed for e in entries if start <= e.date_filed <= through),
            default=start - timedelta(days=1),
        )
    # COPY streams one row at a time and uses this session's transaction. A failed
    # baseline update rolls back membership replacement as well; no raw filings change.
    session.execute(
        delete(CompletenessIndexMember).where(
            CompletenessIndexMember.filed_date.between(start, end)
        )
    )
    raw = cast(psycopg.Connection, session.connection().connection.driver_connection)
    with (
        raw.cursor() as cursor,
        cursor.copy(
            "COPY completeness_index_members (accession_no, form_type, filed_date) FROM STDIN"
        ) as copy,
    ):
        for entry in members:
            copy.write_row((entry.accession_no, entry.form_type, entry.date_filed))
    set_state(
        session,
        INDEX_PREFIX + key,
        {
            "year": year,
            "quarter": quarter,
            "counts": counts,
            "daily_counts": daily,
            "membership_version": MEMBERSHIP_VERSION,
            "through": through.isoformat(),
            "checked_at": now_et().isoformat(),
        },
    )
    return counts


def stored_counts(session: Session, year: int, quarter: int) -> dict[str, int]:
    start, end = quarter_bounds(year, quarter)
    counts: dict[str, int] = dict.fromkeys(FAMILIES, 0)
    for form, count in session.execute(
        select(Filing.form_type, func.count())
        .where(
            Filing.filed_date.between(start, end),
            Filing.parse_status == "parsed",
        )
        .group_by(Filing.form_type)
    ):
        family = family_for(form)
        if family is not None:
            counts[family] += count
    return counts


def unavailable_accessions(session: Session) -> list[UnavailableAccessionOut]:
    records = [
        UnavailableAccessionOut.model_validate(row)
        for row in session.scalars(
            select(AppState.value).where(AppState.key.startswith(ATTEMPT_PREFIX))
        )
        if row.get("status") == "unavailable"
    ]
    if not records:
        return []
    parsed = set(
        session.scalars(
            select(Filing.accession_no).where(
                Filing.accession_no.in_([row.accession_no for row in records]),
                Filing.parse_status == "parsed",
            )
        )
    )
    return [row for row in records if row.accession_no not in parsed]


def record_accession_failure(
    session: Session, *, accession: str, cik: int, family: FormFamily, day: date, error: str
) -> bool:
    """Persist one failed ingest attempt; return whether its retry budget is exhausted."""
    key = ATTEMPT_PREFIX + accession
    state = get_state(session, key) or {}
    attempts = min(3, int(state.get("attempts", 0)) + 1)
    year, quarter = quarter_of(day)
    unavailable = attempts >= 3
    set_state(
        session,
        key,
        {
            "accession_no": accession,
            "cik": cik,
            "family": family,
            "year": year,
            "quarter": quarter,
            "attempts": attempts,
            "error": error,
            "status": "unavailable" if unavailable else "retryable",
            "updated_at": now_et().isoformat(),
        },
    )
    return unavailable


def record_accession_success(session: Session, accession: str) -> None:
    state = get_state(session, ATTEMPT_PREFIX + accession)
    if state:
        set_state(
            session,
            ATTEMPT_PREFIX + accession,
            {**state, "status": "resolved", "updated_at": now_et().isoformat()},
        )


def _price_loading(session: Session) -> bool:
    active = ("requested", "queued", "running")
    if (
        session.scalar(
            select(JobRequest.id)
            .where(
                JobRequest.kind.in_(("backfill_prices", "prices_daily")),
                JobRequest.status.in_(active),
            )
            .limit(1)
        )
        is not None
    ):
        return True
    if (
        session.scalar(
            select(IngestRun.id)
            .where(
                IngestRun.job.in_(("backfill_prices", "prices_daily")),
                IngestRun.finished_at.is_(None),
            )
            .limit(1)
        )
        is not None
    ):
        return True
    return any(
        "backfill_prices" not in (progress or {}).get("done_steps", [])
        for progress in session.scalars(
            select(JobRequest.progress).where(
                JobRequest.kind == "backfill_all", JobRequest.status.in_(active)
            )
        )
    )


def _price_coverage(session: Session, settings: Settings, as_of: date) -> PriceCoverageOut:
    through = prev_trading_day(as_of)
    symbols = {
        entry.symbol
        for entry in build_price_universe(
            session, backfill_start=settings.backfill_start, as_of=as_of
        )
    }
    covered = set(
        session.scalars(
            select(PriceDaily.symbol).where(
                PriceDaily.symbol.in_(symbols),
                PriceDaily.date == through,
                PriceDaily.close > 0,
                PriceDaily.adj_close > 0,
            )
        )
    )
    total = len(symbols)
    return PriceCoverageOut(
        total=total,
        covered=len(covered),
        pct=len(covered) / total if total else None,
        through=through,
        loading=_price_loading(session),
        missing_symbols=sorted(symbols - covered),
    )


def _returns_coverage(session: Session, as_of: date) -> ReturnsCoverageOut:
    # Use the analytics' exact 126-session horizon, including after-close SEC acceptance.
    cutoff = add_trading_days(prev_trading_day(as_of), -126)
    cutoff_close = session_open_close(cutoff)[1]
    result = {}
    for basis in ("filed", "executed"):
        fallback = Decision.first_trade_date <= cutoff
        if basis == "filed":
            fallback = or_(
                Decision.accepted_at < cutoff_close,
                and_(Decision.accepted_at.is_(None), Decision.filed_date < cutoff),
            )
        maturity = or_(
            DecisionReturn.entry_date <= cutoff, and_(DecisionReturn.entry_date.is_(None), fallback)
        )
        eligible, covered = session.execute(
            select(
                func.count(Decision.id),
                func.count(Decision.id).filter(
                    DecisionReturn.is_complete.is_(True),
                    DecisionReturn.raw_return.is_not(None),
                    or_(DecisionReturn.exit_date.is_(None), DecisionReturn.exit_date < as_of),
                ),
            )
            .outerjoin(
                DecisionReturn,
                and_(
                    DecisionReturn.decision_id == Decision.id,
                    DecisionReturn.basis == basis,
                    DecisionReturn.horizon == "6m",
                ),
            )
            .where(maturity)
        ).one()
        result[basis] = ReturnCoverageOut(
            eligible=eligible, covered=covered, pct=covered / eligible if eligible else None
        )
    return ReturnsCoverageOut(filed=result["filed"], executed=result["executed"])


def _fund_coverage(session: Session, settings: Settings, as_of: date) -> FundCoverageOut:
    ciks = list(
        session.scalars(
            select(FundManager.cik)
            .where(FundManager.is_tracked.is_(True))
            .order_by(FundManager.cik)
        )
    )
    periods = [
        quarter_bounds(year, quarter)[1]
        for year, quarter in quarters_between(settings.backfill_start, as_of)
        if quarter_bounds(year, quarter)[1] + timedelta(days=45) < as_of
    ]
    present = set(
        session.execute(
            select(FundFiling.filer_cik, FundFiling.period_of_report)
            .where(
                FundFiling.filer_cik.in_(ciks),
                FundFiling.period_of_report.in_(periods),
                FundFiling.filed_date < as_of,
            )
            .distinct()
        )
    )
    rows = [
        FundQuarterCoverageOut(
            cik=cik,
            year=period.year,
            quarter=quarter_of(period)[1],
            period=period,
            present=(cik, period) in present,
        )
        for cik in ciks
        for period in periods
    ]
    total, covered = len(rows), sum(row.present for row in rows)
    return FundCoverageOut(
        tracked=len(ciks),
        total=total,
        covered=covered,
        pct=covered / total if total else None,
        quarters=rows,
    )


def completeness_report(
    session: Session, *, as_of: date, settings: Settings | None = None
) -> CompletenessReport:
    """Read stored aggregates and coverage only. Never fetch SEC or price data."""
    settings = settings or get_settings()
    starts = family_starts(settings)
    last = as_of - timedelta(days=1)
    baselines = {
        row["year"] * 4 + row["quarter"]: row
        for row in session.scalars(
            select(AppState.value).where(AppState.key.startswith(INDEX_PREFIX))
        )
    }
    counts: dict[tuple[int, int, str], int] = defaultdict(int)
    matched_counts: dict[tuple[int, int, str], int] = defaultdict(int)
    # Group once, preserving date bounds for partial parser-era quarters and stale indexes.
    daily_stored = list(
        session.execute(
            select(
                Filing.filed_date,
                Filing.form_type,
                func.count(Filing.accession_no),
                func.count(CompletenessIndexMember.accession_no),
            )
            .outerjoin(
                CompletenessIndexMember,
                and_(
                    Filing.accession_no == CompletenessIndexMember.accession_no,
                    Filing.form_type == CompletenessIndexMember.form_type,
                    Filing.filed_date == CompletenessIndexMember.filed_date,
                ),
            )
            .where(
                Filing.filed_date.between(date(2016, 1, 1), last),
                Filing.parse_status == "parsed",
                or_(
                    *(
                        and_(Filing.form_type.in_(forms), Filing.filed_date >= starts[family])
                        for family, forms in FAMILIES.items()
                    )
                ),
            )
            .group_by(Filing.filed_date, Filing.form_type)
        )
    )
    for day, form, count, matched in daily_stored:
        family = family_for(form)
        year, quarter = quarter_of(day)
        counts[year, quarter, str(family)] += count
        matched_counts[year, quarter, str(family)] += matched
    quarters = []
    for year, quarter in quarters_between(date(2016, 1, 1), as_of):
        start, end = quarter_bounds(year, quarter)
        through = min(end, last)
        baseline = baselines.get(year * 4 + quarter)
        frontier = date.fromisoformat(baseline["through"]) if baseline else None
        for family in FAMILIES:
            scoped_start = max(start, starts[family])
            indexed = None
            if (
                baseline
                and baseline.get("membership_version") == MEMBERSHIP_VERSION
                and frontier is not None
                and (frontier >= through or (year, quarter) == quarter_of(as_of))
            ):
                indexed = sum(
                    row.get(family, 0)
                    for day, row in baseline["daily_counts"].items()
                    if scoped_start <= date.fromisoformat(day) <= through
                )
            stored = (matched_counts if indexed is not None else counts)[year, quarter, family]
            pct = min(1.0, stored / indexed) if indexed else None
            if through < starts[family]:
                status = "not_supported"
                indexed, pct = None, None
            elif (year, quarter) == quarter_of(as_of):
                status = "in_progress"
            elif indexed is None:
                status = "unknown"
            else:
                status = (
                    "complete" if indexed == 0 or (pct is not None and pct >= TARGET) else "gap"
                )
            quarters.append(
                QuarterCompletenessOut(
                    year=year,
                    quarter=quarter,
                    family=family,
                    indexed=indexed,
                    stored=stored,
                    pct=pct,
                    status=status,
                    coverage_start=starts[family],
                    through=through,
                    indexed_through=frontier,
                )
            )
    yearly = {
        int(year): count
        for year, count in session.execute(
            select(func.extract("year", InsiderTransaction.transaction_date), func.count())
            .where(
                InsiderTransaction.transaction_date >= settings.backfill_start,
                InsiderTransaction.transaction_date < as_of,
                InsiderTransaction.superseded_by.is_(None),
            )
            .group_by(func.extract("year", InsiderTransaction.transaction_date))
        )
    }
    checked = get_state(session, "completeness_check") or {}
    return CompletenessReport(
        as_of=as_of,
        checked_at=checked.get("checked_at"),
        quarters=quarters,
        insider_transactions=[
            YearTransactionsOut(year=year, count=yearly.get(year, 0))
            for year in range(2016, as_of.year + 1)
        ],
        prices=_price_coverage(session, settings, as_of),
        returns=_returns_coverage(session, as_of),
        funds=_fund_coverage(session, settings, as_of),
        unavailable=unavailable_accessions(session),
    )


def _has_retryable_gap(session: Session, archive: RawArchive, row: QuarterCompletenessOut) -> bool:
    body = archive.get("full_index", f"{row.year}Q{row.quarter}", "idx")
    entries = [
        e
        for e in _index_entries(body)
        if e.form_type in FAMILIES[row.family] and row.coverage_start <= e.date_filed <= row.through
    ]
    stored = set(
        session.execute(
            select(Filing.accession_no, Filing.form_type, Filing.filed_date).where(
                Filing.form_type.in_(FAMILIES[row.family]),
                Filing.parse_status == "parsed",
                Filing.filed_date.between(
                    max(quarter_bounds(row.year, row.quarter)[0], row.coverage_start), row.through
                ),
            )
        )
    )
    unavailable = {item.accession_no for item in unavailable_accessions(session)}
    return any(
        (e.accession_no, e.form_type, e.date_filed) not in stored
        and e.accession_no not in unavailable
        for e in entries
    )


def _save_summary(session: Session, report: CompletenessReport) -> None:
    set_state(
        session,
        "completeness_summary",
        {
            "checked_at": report.checked_at.isoformat() if report.checked_at else None,
            "gaps": sum(row.status == "gap" for row in report.quarters),
            "unavailable": len(report.unavailable),
        },
    )


@register_job("completeness_check", cron={"day_of_week": "sun", "hour": 6, "minute": 0})
def completeness_check(ctx: JobContext) -> dict:
    as_of = ctx.now().astimezone(ET).date()
    errors, queued = [], []
    for year, quarter in quarters_between(
        max(date(2016, 1, 1), ctx.settings.backfill_start), as_of
    ):
        try:
            with session_scope(ctx.session_factory) as session:
                index_counts(
                    session, ctx.sec, ctx.archive, year, quarter, as_of=as_of, settings=ctx.settings
                )
        except SecBlockedError:
            raise
        except Exception as exc:
            errors.append(f"{year}Q{quarter}: {type(exc).__name__}: {exc}")
    with session_scope(ctx.session_factory) as session:
        report = completeness_report(session, as_of=as_of, settings=ctx.settings)
        for row in report.quarters:
            if row.status == "gap" and _has_retryable_gap(session, ctx.archive, row):
                queued.append(
                    request_job(
                        session,
                        "gap_fill",
                        {"family": row.family, "year": row.year, "quarter": row.quarter},
                    )
                )
        if not errors:
            set_state(session, "completeness_check", {"checked_at": ctx.now().isoformat()})
            report.checked_at = ctx.now()
        _save_summary(session, report)
    return {"queued": sorted(set(queued)), "errors": len(errors), "error_details": errors}


@register_job("gap_fill")
def gap_fill_job(ctx: JobContext) -> dict:
    from dataclasses import asdict

    from signals.ingest.gap_fill import gap_fill

    family = ctx.params["family"]
    if family not in FAMILIES:
        raise ValueError(f"Unknown form family: {family}")
    start, end = quarter_bounds(int(ctx.params["year"]), int(ctx.params["quarter"]))
    start = max(start, family_starts(ctx.settings)[family])
    end = min(end, ctx.now().astimezone(ET).date() - timedelta(days=1))
    result = asdict(
        gap_fill(
            ctx.sec,
            ctx.session_factory,
            form_types=FAMILIES[family],
            start=start,
            end=end,
            settings=ctx.settings,
            archive=ctx.archive,
            progress=ctx.progress,
            save_progress=ctx.save_progress,
        )
    )
    with session_scope(ctx.session_factory) as session:
        _save_summary(
            session,
            completeness_report(
                session, as_of=ctx.now().astimezone(ET).date(), settings=ctx.settings
            ),
        )
    return result
