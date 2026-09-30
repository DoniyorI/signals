"""Incremental daily-price loader with a fallback provider (spec 7.8).

Each symbol resumes from the day after its last stored bar (or the universe's start,
whichever is later), so a rerun only fetches what's missing -- idempotent, per the ground
rules. Nothing is ever invented: a symbol neither provider has data for is reported in
`missing` rather than left silently absent.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, cast

import httpx
import pandas as pd
from sqlalchemy import Table, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from signals.config import Settings
from signals.db.models import PriceDaily
from signals.db.session import session_scope
from signals.prices.alpaca import AlpacaProvider
from signals.prices.base import PriceProvider
from signals.prices.universe import UniverseEntry
from signals.prices.yfinance_provider import YFinanceProvider

BAR_VALUE_COLUMNS = ("open", "high", "low", "close", "volume", "adj_close")


@dataclass(frozen=True)
class LoadPricesResult:
    requested: int
    loaded: int
    rows: int
    missing: tuple[str, ...]
    fallback_used: tuple[str, ...]


def make_providers(
    settings: Settings, http: httpx.Client | None = None
) -> tuple[PriceProvider, PriceProvider | None]:
    """Alpaca (with yfinance as its fallback) when configured and keyed; otherwise
    yfinance alone -- the free Alpaca key check (foundation) already redirected
    `price_primary` to "yfinance" when SIP access isn't permitted."""
    if (
        settings.price_primary == "alpaca"
        and settings.alpaca_api_key
        and settings.alpaca_secret_key
    ):
        client = http if http is not None else httpx.Client()
        primary: PriceProvider = AlpacaProvider(
            client,
            settings.alpaca_api_key,
            settings.alpaca_secret_key.get_secret_value(),
            feed=settings.alpaca_feed,
            base_url=settings.alpaca_data_url,
        )
        return primary, YFinanceProvider()
    return YFinanceProvider(), None


def _last_dates(session: Session, symbols: Sequence[str]) -> dict[str, date]:
    rows = session.execute(
        select(PriceDaily.symbol, func.max(PriceDaily.date))
        .where(PriceDaily.symbol.in_(list(symbols)))
        .group_by(PriceDaily.symbol)
    ).all()
    return dict(rows)


def _effective_starts(session: Session, universe: Sequence[UniverseEntry]) -> dict[str, date]:
    last = _last_dates(session, [e.symbol for e in universe])
    starts: dict[str, date] = {}
    for entry in universe:
        prior = last.get(entry.symbol)
        starts[entry.symbol] = max(entry.start, prior + timedelta(days=1)) if prior else entry.start
    return starts


def _group_by_start(starts: Mapping[str, date]) -> dict[date, list[str]]:
    groups: dict[date, list[str]] = {}
    for symbol, start in starts.items():
        groups.setdefault(start, []).append(symbol)
    return groups


def _upsert_bars(session: Session, df: pd.DataFrame, source: str) -> int:
    if df.empty:
        return 0
    table = cast(Table, PriceDaily.__table__)
    records: list[dict[str, Any]] = [
        {**{c: row[c] for c in ("symbol", "date", *BAR_VALUE_COLUMNS)}, "source": source}
        for row in df.to_dict("records")
    ]
    stmt = insert(table).values(records)
    update_cols = {c: stmt.excluded[c] for c in (*BAR_VALUE_COLUMNS, "source")}
    stmt = stmt.on_conflict_do_update(
        index_elements=[table.c.symbol, table.c.date], set_=update_cols
    )
    session.execute(stmt)
    return len(records)


def _fetch_and_store(
    session_factory: Callable[[], Session],
    provider: PriceProvider,
    groups: Mapping[date, list[str]],
    end: date,
) -> tuple[int, set[str]]:
    """Fetch and upsert one batch per start date; one commit per batch (spec 7.8)."""
    rows = 0
    have_data: set[str] = set()
    for start, symbols in groups.items():
        df = provider.daily_bars(symbols, start, end)
        with session_scope(session_factory) as s:
            rows += _upsert_bars(s, df, provider.name)
        have_data.update(df["symbol"].unique().tolist())
    return rows, have_data


def load_prices(
    session_factory: Callable[[], Session],
    primary: PriceProvider,
    fallback: PriceProvider | None,
    universe: Sequence[UniverseEntry],
    *,
    end: date,
) -> LoadPricesResult:
    with session_scope(session_factory) as s:
        starts = _effective_starts(s, universe)

    # A symbol already loaded through `end` needs nothing this run.
    pending = {symbol: start for symbol, start in starts.items() if start <= end}

    rows, have_data = _fetch_and_store(session_factory, primary, _group_by_start(pending), end)

    needing_fallback = {
        symbol: start for symbol, start in pending.items() if symbol not in have_data
    }
    fallback_used: set[str] = set()
    if fallback is not None and needing_fallback:
        fb_rows, fb_have = _fetch_and_store(
            session_factory, fallback, _group_by_start(needing_fallback), end
        )
        rows += fb_rows
        have_data.update(fb_have)
        fallback_used.update(fb_have)

    missing = sorted(set(needing_fallback) - fallback_used)
    return LoadPricesResult(
        requested=len(universe),
        loaded=len(pending),
        rows=rows,
        missing=tuple(missing),
        fallback_used=tuple(sorted(fallback_used)),
    )
