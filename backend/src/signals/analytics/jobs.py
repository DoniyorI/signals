"""Analytics jobs (workstream D): the nightly full run (also the last backfill step) and
incremental runs requested after ingest batches (params `issuer_ciks` and `owner_ciks`).

Both run as of today in US Eastern time, report each step through the job's progress and
write an `ingest_runs` row, including when they fail.
"""

from dataclasses import asdict
from typing import Any

from signals.analytics.run import Progress, RunResult, run_full, run_incremental
from signals.jobs import JobContext, RunTracker, register_job, track_run


def _progress(ctx: JobContext) -> Progress:
    def report(step: str) -> None:
        ctx.progress["step"] = step
        ctx.save_progress(ctx.progress)

    return report


def _summary(run: RunTracker, result: RunResult) -> dict[str, Any]:
    summary = asdict(result)
    run.notes.update(summary)
    return summary


def _ciks(ctx: JobContext, key: str) -> list[int]:
    return [int(c) for c in ctx.params.get(key) or []]


@register_job("analytics_full", cron={"hour": 2, "minute": 0})
def analytics_full(ctx: JobContext) -> dict[str, Any]:
    with track_run(ctx.session_factory, "analytics_full") as run:
        result = run_full(ctx.session_factory, as_of=ctx.now().date(), progress=_progress(ctx))
        return _summary(run, result)


@register_job("analytics_incremental")
def analytics_incremental(ctx: JobContext) -> dict[str, Any]:
    with track_run(ctx.session_factory, "analytics_incremental") as run:
        result = run_incremental(
            ctx.session_factory,
            issuer_ciks=_ciks(ctx, "issuer_ciks"),
            owner_ciks=_ciks(ctx, "owner_ciks"),
            as_of=ctx.now().date(),
            progress=_progress(ctx),
        )
        return _summary(run, result)
