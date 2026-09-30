"""Price universe (spec 7.8) and the incremental loader with fallback."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from sqlalchemy import select

from signals.db.models import FundPosition, PriceDaily
from signals.domain.tickers import rebuild_tickers, record_ticker_evidence
from signals.domain.types import SECTOR_ETF
from signals.prices.loader import load_prices
from signals.prices.universe import UniverseEntry, build_price_universe
from tests.factories import (
    make_filing,
    make_fund_filing,
    make_fund_manager,
    make_issuer,
    make_prices,
    make_security,
    make_transaction,
)

BARS_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume", "adj_close")


@dataclass
class FakeCall:
    symbols: list[str]
    start: date
    end: date


@dataclass
class FakeProvider:
    name: str
    bars: dict[str, list[dict]] = field(default_factory=dict)
    calls: list[FakeCall] = field(default_factory=list)

    def daily_bars(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        """Like a real provider, only returns bars inside [start, end]."""
        self.calls.append(FakeCall(list(symbols), start, end))
        rows = [
            {**bar, "symbol": symbol}
            for symbol in symbols
            for bar in self.bars.get(symbol, [])
            if start <= bar["date"] <= end
        ]
        return pd.DataFrame(rows, columns=list(BARS_COLUMNS))


def _bar(day: date, close: float) -> dict:
    return {
        "date": day,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 100.0,
        "adj_close": close,
    }


def test_universe_includes_benchmarks_and_both_tickers(session):
    make_issuer(session, cik=9000001, name="Old Co", ticker=None)
    record_ticker_evidence(session, 9000001, "GBX", date(2016, 1, 4), "test")
    record_ticker_evidence(session, 9000001, "GLBX", date(2022, 6, 1), "test")
    rebuild_tickers(session, [9000001])
    filing_acc = "0009000001-23-000001"
    make_filing(session, accession_no=filing_acc, issuer_cik=9000001)
    make_transaction(
        session, accession_no=filing_acc, issuer_cik=9000001, transaction_date=date(2023, 5, 1)
    )

    universe = build_price_universe(session, backfill_start=date(2016, 1, 1))
    symbols = {e.symbol for e in universe}
    assert {"GBX", "GLBX", "SPY", "QQQ", "XLK"}.issubset(symbols)
    assert set(SECTOR_ETF.values()).issubset(symbols)


def test_universe_includes_tracked_fund_holdings(session):
    manager = make_fund_manager(session, cik=3100001, is_tracked=True)
    filing = make_fund_filing(session, accession_no="0003100001-24-000001", filer_cik=manager.cik)
    make_security(session, cusip="111111AA1", ticker="TRKD")
    session.add(
        FundPosition(
            period=filing.period_of_report,
            accession_no=filing.accession_no,
            cusip="111111AA1",
            put_call="",
            filer_cik=manager.cik,
            shares=100.0,
            is_effective=True,
        )
    )
    session.flush()

    universe = build_price_universe(session, backfill_start=date(2016, 1, 1))
    assert "TRKD" in {e.symbol for e in universe}


def test_incremental_start(session, session_factory):
    make_prices(session, "ACME", date(2024, 1, 2), [1.0] * 7)
    primary = FakeProvider(name="fake_primary")
    universe = [UniverseEntry(symbol="ACME", start=date(2024, 1, 2))]

    load_prices(session_factory, primary, None, universe, end=date(2024, 1, 31))

    assert len(primary.calls) == 1
    assert primary.calls[0].start == date(2024, 1, 10)  # overlap checks the adjustment factor
    assert primary.calls[0].end == date(2024, 1, 31)


def test_fallback_and_missing(session, session_factory):
    primary = FakeProvider(name="fake_primary", bars={})
    fallback = FakeProvider(name="fake_fallback", bars={"OLD": [_bar(date(2024, 1, 2), 10.0)]})
    universe = [
        UniverseEntry(symbol="OLD", start=date(2024, 1, 1)),
        UniverseEntry(symbol="GONE", start=date(2024, 1, 1)),
    ]

    result = load_prices(session_factory, primary, fallback, universe, end=date(2024, 1, 31))

    assert result.fallback_used == ("OLD",)
    assert result.missing == ("GONE",)
    stored = session.scalars(select(PriceDaily).where(PriceDaily.symbol == "OLD")).all()
    assert len(stored) == 1 and stored[0].source == "fake_fallback"


def test_idempotent(session, session_factory):
    make_prices(session, "ACME", date(2024, 1, 2), [1.0] * 7)  # through 2024-01-10
    primary = FakeProvider(
        name="fake_primary",
        bars={"ACME": [_bar(date(2024, 1, 11), 2.0), _bar(date(2024, 1, 12), 2.1)]},
    )
    universe = [UniverseEntry(symbol="ACME", start=date(2024, 1, 2))]

    first = load_prices(session_factory, primary, None, universe, end=date(2024, 1, 31))
    assert first.rows == 2  # the two new bars past what was already stored

    second = load_prices(session_factory, primary, None, universe, end=date(2024, 1, 31))
    assert second.rows == 0  # rerunning the same job inserts nothing new
