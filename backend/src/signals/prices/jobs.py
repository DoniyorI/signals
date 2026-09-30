"""Price jobs. Owned by workstream C."""

from datetime import date, timedelta

from signals.db.session import session_scope
from signals.domain.appstate import set_state
from signals.domain.calendars import is_trading_day
from signals.jobs import JobContext, register_job
from signals.prices.loader import load_prices, make_providers
from signals.prices.universe import build_price_universe

PRICES_STATE_KEY = "prices_last"


def _load_prices_through(ctx: JobContext, end: date) -> dict:
    with session_scope(ctx.session_factory) as s:
        universe = build_price_universe(s, backfill_start=ctx.settings.backfill_start)
    primary, fallback = make_providers(ctx.settings)
    result = load_prices(ctx.session_factory, primary, fallback, universe, end=end)
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
