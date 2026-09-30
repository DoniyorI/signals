"""Incremental daily-price loader with a fallback provider (spec 7.8).

Each run overlaps the last stored bar to detect changed raw or adjusted prices. A split or
dividend triggers a history refresh for that symbol, atomically with its new bars. An
explicit history refresh also repairs older vendor corrections and price gaps. Fetches
and writes are bounded; unchanged rows are not rewritten. Missing prices stay missing.
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from math import isclose
from typing import Any, cast

import httpx
import pandas as pd
from sqlalchemy import Table, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from signals.config import Settings
from signals.db.models import PriceDaily
from signals.db.session import session_scope
from signals.domain.appstate import get_state, set_state
from signals.prices.alpaca import AlpacaProvider
from signals.prices.base import PriceProvider
from signals.prices.universe import UniverseEntry
from signals.prices.yfinance_provider import YFinanceProvider

BAR_VALUE_COLUMNS = ("open", "high", "low", "close", "volume", "adj_close")
UPSERT_ROWS = 1000
FETCH_SYMBOLS = 25
FETCH_DAYS = 366
PRICES_LOCK_KEY = 0x5349_474E_5052_4301
HISTORY_STARTS_KEY = "prices_history_starts"
HISTORY_ENDS_KEY = "prices_history_ends"


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


@dataclass(frozen=True)
class StoredHistory:
    first: date
    last: date
    close: float
    adj_close: float


def _history(session: Session, symbols: Sequence[str]) -> dict[str, StoredHistory]:
    bounds = (
        select(
            PriceDaily.symbol,
            func.min(PriceDaily.date).label("first"),
            func.max(PriceDaily.date).label("last"),
        )
        .where(PriceDaily.symbol.in_(list(symbols)))
        .group_by(PriceDaily.symbol)
        .subquery()
    )
    rows = session.execute(
        select(
            bounds.c.symbol, bounds.c.first, bounds.c.last, PriceDaily.close, PriceDaily.adj_close
        ).join(
            PriceDaily,
            (PriceDaily.symbol == bounds.c.symbol) & (PriceDaily.date == bounds.c.last),
        )
    ).all()
    return {
        symbol: StoredHistory(first, last, close, adjusted)
        for symbol, first, last, close, adjusted in rows
    }


def _effective_starts(
    session: Session, universe: Sequence[UniverseEntry], *, refresh_history: bool
) -> dict[str, date]:
    history = _history(session, [e.symbol for e in universe])
    attempted = get_state(session, HISTORY_STARTS_KEY) or {}
    starts: dict[str, date] = {}
    for entry in universe:
        prior = history.get(entry.symbol)
        tried = date.fromisoformat(attempted[entry.symbol]) if entry.symbol in attempted else None
        if prior is None or (entry.start < prior.first and (tried is None or entry.start < tried)):
            starts[entry.symbol] = entry.start
        elif refresh_history:
            starts[entry.symbol] = min(entry.start, prior.first)
        else:
            starts[entry.symbol] = prior.last
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
    changed = 0
    for offset in range(0, len(df), UPSERT_ROWS):
        records: list[dict[str, Any]] = [
            {**{c: row[c] for c in ("symbol", "date", *BAR_VALUE_COLUMNS)}, "source": source}
            for row in df.iloc[offset : offset + UPSERT_ROWS].to_dict("records")
        ]
        stmt = insert(table).values(records)
        update_cols = {c: stmt.excluded[c] for c in (*BAR_VALUE_COLUMNS, "source")}
        stmt = stmt.on_conflict_do_update(
            index_elements=[table.c.symbol, table.c.date],
            set_=update_cols,
            where=or_(*(table.c[c].is_distinct_from(stmt.excluded[c]) for c in update_cols)),
        )
        changed += len(session.execute(stmt.returning(table.c.symbol)).all())
    return changed


def _fetch_and_store(
    session_factory: Callable[[], Session],
    provider: PriceProvider,
    groups: Mapping[date, list[str]],
    end: date,
    universe: Mapping[str, date],
    *,
    refresh_history: bool,
) -> tuple[int, set[str]]:
    """Commit bounded symbol batches; revisions and their sentinel share a transaction."""
    rows = 0
    have_data: set[str] = set()
    for start, symbols in groups.items():
        for offset in range(0, len(symbols), FETCH_SYMBOLS):
            batch = symbols[offset : offset + FETCH_SYMBOLS]
            # Cron and requested price jobs can overlap. Do not compare a sentinel from
            # before another writer's refresh or expose a partially rebased history.
            with session_scope(session_factory) as s:
                s.execute(select(func.pg_advisory_xact_lock(PRICES_LOCK_KEY)))
                history = _history(s, batch)
                attempted = get_state(s, HISTORY_STARTS_KEY) or {}
                checked = get_state(s, HISTORY_ENDS_KEY) or {}
                full = [symbol for symbol, prior in history.items() if start <= prior.first]
                expected: dict[str, set[date]] = {}
                if full:
                    for symbol, day in s.execute(
                        select(PriceDaily.symbol, PriceDaily.date).where(
                            PriceDaily.symbol.in_(full), PriceDaily.date <= end
                        )
                    ):
                        expected.setdefault(symbol, set()).add(day)
                actual: dict[str, set[date]] = {}
                batch_have: set[str] = set()
                for df in _batch_frames(
                    provider, batch, start, end, history, checked, refresh_history=refresh_history
                ):
                    for bar in df.to_dict("records"):
                        actual.setdefault(bar["symbol"], set()).add(bar["date"])
                        prior = history.get(bar["symbol"])
                        if prior is None or bar["date"] != prior.last or start <= prior.first:
                            continue
                        # Yahoo may revise raw OHLC together with adjusted close after
                        # a split. The adjustment ratio alone would remain unchanged.
                        if not isclose(bar["close"], prior.close, rel_tol=1e-8) or not isclose(
                            bar["adj_close"], prior.adj_close, rel_tol=1e-8
                        ):
                            rows += _refresh_symbol(
                                s,
                                provider,
                                bar["symbol"],
                                min(universe[bar["symbol"]], prior.first),
                                end,
                            )
                    rows += _upsert_bars(s, df, provider.name)
                    batch_have.update(df["symbol"].unique().tolist())
                for symbol in batch_have & expected.keys():
                    _check_refresh(symbol, expected[symbol], actual[symbol])
                # A provider's first actual bar can be after the requested start (IPO,
                # listing or limited coverage). Remember a completed attempt so a cron
                # run does not download that same empty prefix every day.
                for symbol in batch_have:
                    prior_start = (
                        date.fromisoformat(attempted[symbol]) if symbol in attempted else start
                    )
                    attempted[symbol] = min(start, prior_start).isoformat()
                    prior_end = date.fromisoformat(checked[symbol]) if symbol in checked else end
                    checked[symbol] = max(end, prior_end).isoformat()
                if batch_have:
                    set_state(s, HISTORY_STARTS_KEY, attempted)
                    set_state(s, HISTORY_ENDS_KEY, checked)
                have_data.update(batch_have)
    return rows, have_data


def _batch_frames(
    provider: PriceProvider,
    symbols: Sequence[str],
    start: date,
    end: date,
    history: Mapping[str, StoredHistory],
    checked: Mapping[str, str],
    *,
    refresh_history: bool,
) -> Iterator[pd.DataFrame]:
    spans: dict[tuple[date, date], list[str]] = {}
    for symbol in symbols:
        prior = history.get(symbol)
        through = date.fromisoformat(checked[symbol]) if symbol in checked else None
        if (
            not refresh_history
            and prior is not None
            and start == prior.last
            and through is not None
            and through > start
        ):
            spans.setdefault((start, start), []).append(symbol)
            fresh = through + timedelta(days=1)
            if fresh <= end:
                spans.setdefault((fresh, end), []).append(symbol)
        else:
            spans.setdefault((start, end), []).append(symbol)
    for (first, last), batch in spans.items():
        yield from _frames(provider, batch, first, last)


def _frames(
    provider: PriceProvider, symbols: Sequence[str], start: date, end: date
) -> Iterator[pd.DataFrame]:
    while start <= end:
        stop = min(end, start + timedelta(days=FETCH_DAYS - 1))
        yield provider.daily_bars(symbols, start, stop)
        start = stop + timedelta(days=1)


def _refresh_symbol(
    session: Session, provider: PriceProvider, symbol: str, start: date, end: date
) -> int:
    expected = set(
        session.scalars(
            select(PriceDaily.date).where(
                PriceDaily.symbol == symbol, PriceDaily.date >= start, PriceDaily.date <= end
            )
        )
    )
    actual: set[date] = set()
    rows = 0
    for df in _frames(provider, [symbol], start, end):
        actual.update(df["date"].tolist())
        rows += _upsert_bars(session, df, provider.name)
    _check_refresh(symbol, expected, actual)
    return rows


def _check_refresh(symbol: str, expected: set[date], actual: set[date]) -> None:
    if missing := expected - actual:
        raise RuntimeError(
            f"Incomplete adjusted-price refresh for {symbol}: missing {len(missing)} stored bars"
        )


def load_prices(
    session_factory: Callable[[], Session],
    primary: PriceProvider,
    fallback: PriceProvider | None,
    universe: Sequence[UniverseEntry],
    *,
    end: date,
    refresh_history: bool = False,
) -> LoadPricesResult:
    with session_scope(session_factory) as s:
        starts = _effective_starts(s, universe, refresh_history=refresh_history)

    # Up-to-date symbols still probe their last bar for adjustment revisions.
    pending = {symbol: start for symbol, start in starts.items() if start <= end}

    universe_starts = {entry.symbol: entry.start for entry in universe}
    rows, have_data = _fetch_and_store(
        session_factory,
        primary,
        _group_by_start(pending),
        end,
        universe_starts,
        refresh_history=refresh_history,
    )

    needing_fallback = {
        symbol: start for symbol, start in pending.items() if symbol not in have_data
    }
    fallback_used: set[str] = set()
    if fallback is not None and needing_fallback:
        fb_rows, fb_have = _fetch_and_store(
            session_factory,
            fallback,
            _group_by_start(needing_fallback),
            end,
            universe_starts,
            refresh_history=refresh_history,
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
