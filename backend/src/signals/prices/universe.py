"""The price universe: every symbol prices must be loaded for (spec 7.8).

The union, deduplicated by symbol with the minimum start, of:
1. Every `tickers` interval of an issuer with a Form 4 transaction since `backfill_start`,
   restricted to intervals overlapping `[backfill_start, today]`.
2. `securities.ticker` for CUSIPs held (effective positions) by tracked funds.
3. `BENCHMARK_SYMBOLS` (SPY, QQQ, the 11 sector ETFs).
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from signals.db.models import FundManager, FundPosition, InsiderTransaction, Security, Ticker
from signals.domain.calendars import now_et
from signals.domain.tickers import canonical_symbol
from signals.domain.types import BENCHMARK_SYMBOLS

PRICE_LOOKBACK = timedelta(days=120)


@dataclass(frozen=True)
class UniverseEntry:
    symbol: str
    start: date


def _traded_ticker_intervals(session: Session, backfill_start: date) -> list[tuple[str, date]]:
    """(symbol, start) for tickers of issuers with a tracked Form 4 transaction, restricted
    to ticker intervals overlapping [backfill_start, today]."""
    today = now_et().date()
    traded_issuers = (
        select(InsiderTransaction.issuer_cik)
        .where(InsiderTransaction.transaction_date >= backfill_start)
        .distinct()
    )
    rows = session.execute(
        select(Ticker.symbol, Ticker.valid_from).where(
            Ticker.issuer_cik.in_(traded_issuers),
            Ticker.valid_from <= today,
            or_(Ticker.valid_to.is_(None), Ticker.valid_to >= backfill_start),
        )
    ).all()
    floor = backfill_start - PRICE_LOOKBACK
    return [(symbol, max(floor, valid_from)) for symbol, valid_from in rows]


def _tracked_fund_tickers(session: Session) -> list[str]:
    """Tickers of securities in effective positions held by tracked funds."""
    rows = session.scalars(
        select(Security.ticker)
        .join(FundPosition, FundPosition.cusip == Security.cusip)
        .join(FundManager, FundManager.cik == FundPosition.filer_cik)
        .where(
            FundManager.is_tracked.is_(True),
            FundPosition.is_effective.is_(True),
            Security.ticker.is_not(None),
        )
        .distinct()
    )
    return [ticker for ticker in rows if ticker is not None]


def build_price_universe(session: Session, *, backfill_start: date) -> list[UniverseEntry]:
    floor = backfill_start - PRICE_LOOKBACK
    best: dict[str, date] = {}

    def add(raw_symbol: str | None, start: date) -> None:
        symbol = canonical_symbol(raw_symbol) if raw_symbol else None
        if symbol is None:
            return
        if symbol not in best or start < best[symbol]:
            best[symbol] = start

    for symbol, start in _traded_ticker_intervals(session, backfill_start):
        add(symbol, start)
    for symbol in _tracked_fund_tickers(session):
        add(symbol, floor)
    for symbol in BENCHMARK_SYMBOLS:
        add(symbol, floor)

    return [UniverseEntry(symbol=s, start=d) for s, d in sorted(best.items())]
