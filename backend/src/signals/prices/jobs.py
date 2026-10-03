"""Price jobs. Owned by workstream C."""

from dataclasses import asdict
from datetime import date, timedelta

from signals.db.session import session_scope
from signals.domain.appstate import set_state
from signals.domain.calendars import is_trading_day
from signals.jobs import JobContext, register_job
from signals.prices.loader import FETCH_SYMBOLS, load_prices, make_providers
from signals.prices.universe import build_insider_price_universe, build_price_universe

PRICES_STATE_KEY = "prices_last"


def _load_prices_through(ctx: JobContext, end: date) -> dict:
    with session_scope(ctx.session_factory) as s:
        universe = build_price_universe(s, backfill_start=ctx.settings.backfill_start)
    primary, fallback = make_providers(ctx.settings)
    result = load_prices(
        ctx.session_factory,
        primary,
        fallback,
        universe,
        end=end,
        refresh_history=ctx.params.get("refresh_history") is True,
    )
    payload = {
        "requested": result.requested,
        "loaded": result.loaded,
        "rows": result.rows,
        "missing": list(result.missing),
        "fallback_used": list(result.fallback_used),
        "end": end.isoformat(),
    }
    with session_scope(ctx.session_factory) as s:
        set_state(s, PRICES_STATE_KEY, payload)
    return payload


@register_job("backfill_prices")
def backfill_prices(ctx: JobContext) -> dict:
    yesterday = ctx.now().date() - timedelta(days=1)
    return _load_prices_through(ctx, yesterday)


@register_job("prices_daily", cron={"day_of_week": "mon-fri", "hour": 18, "minute": 30})
def prices_daily(ctx: JobContext) -> dict:
    today = ctx.now().date()
    end = today if is_trading_day(today) else today - timedelta(days=1)
    return _load_prices_through(ctx, end)


@register_job("refresh_insider_performance")
def refresh_insider_performance(ctx: JobContext) -> dict:
    """Demand-loaded chart inputs, serialized with bulk maintenance by the worker.

    Scoped progress belongs to this request; it never advances the global price or
    full-backfill checkpoints. Existing bounded, idempotent loaders reuse stored bars.
    """
    from signals.analytics.run import run_insider_profile

    owner = ctx.params.get("owner_cik")
    if type(owner) is not int or owner <= 0:
        raise ValueError("owner_cik must be a positive integer")
    end = ctx.now().date() - timedelta(days=1)
    with session_scope(ctx.session_factory) as s:
        universe = build_insider_price_universe(
            s, owner_cik=owner, backfill_start=ctx.settings.backfill_start, as_of=end
        )
    ctx.progress.update(
        owner_cik=owner, stage="prices", symbols_total=len(universe), symbols_done=0, missing=[]
    )
    ctx.save_progress(ctx.progress)
    primary, fallback = make_providers(ctx.settings)
    rows = 0
    for offset in range(0, len(universe), FETCH_SYMBOLS):
        batch = universe[offset : offset + FETCH_SYMBOLS]
        result = load_prices(ctx.session_factory, primary, fallback, batch, end=end)
        rows += result.rows
        ctx.progress["symbols_done"] += len(batch)
        ctx.progress["missing"].extend(result.missing)
        ctx.save_progress(ctx.progress)
    ctx.progress["stage"] = "analytics"
    ctx.save_progress(ctx.progress)

    def report(step: str) -> None:
        ctx.progress["step"] = step
        ctx.save_progress(ctx.progress)

    result = run_insider_profile(ctx.session_factory, owner_cik=owner, as_of=end, progress=report)
    ctx.progress["stage"] = "done"
    ctx.save_progress(ctx.progress)
    return {
        "owner_cik": owner,
        "rows": rows,
        "missing": ctx.progress["missing"],
        "analytics": asdict(result),
    }
