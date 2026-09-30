"""Reference-data jobs. Owned by workstream C.

`backfill_reference` is resumable (spec 7.4): each unit -- the submissions.zip load, the
company_tickers_exchange.json load, and each quarter's shares frame -- is marked done in
`ctx.progress` as it completes, so a request that's re-run after a crash skips work already
done. That only matters for the on-request `backfill_reference`: scheduled jobs
(`reference_refresh`, `tickers_refresh`) always start from an empty progress dict (the
worker's cron context discards it), which is fine since they're small enough to just rerun.
"""

from collections.abc import Iterable
from datetime import date

from signals.db.session import session_scope
from signals.jobs import JobContext, register_job
from signals.reference.companies import load_company_tickers_exchange, load_submissions_zip
from signals.reference.sectors import assign_sectors
from signals.reference.shares import frames_url, load_shares_frames
from signals.sec.client import SecNotFoundError

SUBMISSIONS_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
FIRST_FRAME_YEAR, FIRST_FRAME_QUARTER = 2016, 1


def _frame_quarters(today: date, *, last_n: int | None = None) -> list[tuple[int, int]]:
    """(year, quarter) pairs from 2016Q1 through the last fully completed calendar quarter
    (a quarter that started this month or later hasn't been published yet). `last_n` keeps
    only the most recent quarters, for the weekly refresh."""
    current_q = (today.month - 1) // 3 + 1
    last_year, last_q = today.year, current_q - 1
    if last_q == 0:
        last_year, last_q = last_year - 1, 4
    quarters: list[tuple[int, int]] = []
    y, q = FIRST_FRAME_YEAR, FIRST_FRAME_QUARTER
    while (y, q) <= (last_year, last_q):
        quarters.append((y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return quarters[-last_n:] if last_n is not None and last_n < len(quarters) else quarters


def _load_submissions(ctx: JobContext) -> None:
    zip_path = ctx.settings.raw_archive_dir / "reference" / "submissions.zip"
    ctx.sec.download(SUBMISSIONS_URL, zip_path)
    with session_scope(ctx.session_factory) as s:
        load_submissions_zip(s, zip_path, seen_on=ctx.now().date())


def _load_company_tickers(ctx: JobContext) -> None:
    data = ctx.sec.get(
        COMPANY_TICKERS_URL, archive_as=("reference", "company_tickers_exchange", "json")
    )
    with session_scope(ctx.session_factory) as s:
        load_company_tickers_exchange(s, data, seen_on=ctx.now().date())


def _load_frame(ctx: JobContext, year: int, quarter: int) -> None:
    try:
        data = ctx.sec.get(
            frames_url(year, quarter),
            archive_as=("reference", f"frames-CY{year}Q{quarter}I", "json"),
        )
    except SecNotFoundError:
        return  # not published (yet, or ever, for this quarter) -- not an error
    with session_scope(ctx.session_factory) as s:
        load_shares_frames(s, data)


def _run_reference_steps(ctx: JobContext, quarters: Iterable[tuple[int, int]]) -> dict:
    done: set[str] = set(ctx.progress.get("done", []))

    def mark(unit: str) -> None:
        done.add(unit)
        ctx.progress["done"] = sorted(done)
        ctx.save_progress(ctx.progress)

    if "submissions" not in done:
        _load_submissions(ctx)
        mark("submissions")
    if "company_tickers" not in done:
        _load_company_tickers(ctx)
        mark("company_tickers")
    for year, quarter in quarters:
        unit = f"frames-{year}Q{quarter}"
        if unit in done:
            continue
        _load_frame(ctx, year, quarter)
        mark(unit)
    if "sectors" not in done:
        with session_scope(ctx.session_factory) as s:
            changed = assign_sectors(s)
        ctx.progress["sectors_changed"] = changed
        mark("sectors")

    return {"done": sorted(done), "sectors_changed": ctx.progress.get("sectors_changed", 0)}


@register_job("backfill_reference")
def backfill_reference(ctx: JobContext) -> dict:
    return _run_reference_steps(ctx, _frame_quarters(ctx.now().date()))


@register_job("reference_refresh", cron={"day_of_week": "sun", "hour": 4, "minute": 0})
def reference_refresh(ctx: JobContext) -> dict:
    return _run_reference_steps(ctx, _frame_quarters(ctx.now().date(), last_n=4))


@register_job("tickers_refresh", cron={"hour": 5, "minute": 0})
def tickers_refresh(ctx: JobContext) -> dict:
    _load_company_tickers(ctx)
    return {}
