"""Recorded filings -> production bootstrap -> prices -> analytics -> real API curves."""

from collections.abc import Sequence
from datetime import date, datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from signals.analytics import curves
from signals.analytics.run import run_full
from signals.api.deps import get_db
from signals.api.main import create_app
from signals.api.queries import common
from signals.db.models import (
    FundManager,
    FundPosition,
    InsiderTransaction,
    Issuer,
    Security,
    TickerEvidence,
)
from signals.domain.calendars import ET, trading_days
from signals.domain.tickers import rebuild_tickers, record_ticker_evidence
from signals.ingest import dispatch
from signals.ingest.pipeline import ingest_raw
from signals.jobs import load_all_jobs
from signals.prices.loader import load_prices
from signals.prices.universe import build_price_universe

AS_OF = date(2026, 9, 29)
KEYS = ("form4_buy_single", "form4_joint", "f13f_small")


class RecordedPriceProvider:
    name = "integration_fake"

    def daily_bars(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        rows = []
        for symbol in symbols:
            for day in trading_days(start, end):
                close = 20.0 + (day - date(2024, 1, 1)).days / 1000
                rows.append(
                    {
                        "symbol": symbol,
                        "date": day,
                        "open": close,
                        "high": close,
                        "low": close,
                        "close": close,
                        "volume": 1000.0,
                        "adj_close": close,
                    }
                )
        return pd.DataFrame(
            rows, columns=["symbol", "date", "open", "high", "low", "close", "volume", "adj_close"]
        )


@pytest.fixture(autouse=True)
def clean_curves_and_dispatch():
    curves._curve_slots.cache_clear()
    dispatch.reset_registry()
    yield
    curves._curve_slots.cache_clear()
    dispatch.reset_registry()


def test_filing_to_api_end_to_end(
    session, session_factory, settings, tmp_archive, fixture_bytes, manifest, monkeypatch
):
    # Use the worker bootstrap; importing handlers here would hide the startup defect.
    load_all_jobs()
    for key in KEYS:
        raw = fixture_bytes(key)
        path = tmp_archive.put("filing", manifest[key]["accession"], raw, "txt")
        outcome = ingest_raw(
            session,
            raw,
            source="test",
            raw_path=str(path),
            first_seen_at=None,
            settings=settings,
            archive=tmp_archive,
        )
        assert outcome.status == "parsed", outcome.error

    for issuer in session.scalars(select(Issuer)):
        issuer.sector = "Technology"
    # Reference evidence independently supplies ticker coverage before the first filing.
    for cik in (manifest[k]["expect"]["issuer_cik"] for k in KEYS[:2]):
        evidence = session.scalars(
            select(TickerEvidence).where(TickerEvidence.issuer_cik == cik)
        ).one()
        record_ticker_evidence(session, cik, evidence.symbol, date(2024, 1, 1), "test_reference")
    rebuild_tickers(session)
    fund_cik = manifest["f13f_small"]["cik"]
    manager = session.get(FundManager, fund_cik)
    assert manager is not None
    manager.is_tracked = True
    cusips = list(
        session.scalars(select(FundPosition.cusip).distinct().order_by(FundPosition.cusip))
    )
    assert len(cusips) > 0
    for index, cusip in enumerate(cusips):
        security = session.get(Security, cusip)
        if security is None:
            security = Security(cusip=cusip)
            session.add(security)
        security.ticker = f"TEST{index}"
        security.map_status = "mapped"
        security.map_source = "test_reference"
    session.flush()

    universe = build_price_universe(session, backfill_start=date(2025, 1, 1))
    assert {"SPY", "QQQ", "XLK"} <= {entry.symbol for entry in universe}
    loaded = load_prices(session_factory, RecordedPriceProvider(), None, universe, end=AS_OF)
    assert loaded.rows > 0
    session.commit()
    computed = run_full(session_factory, as_of=AS_OF)
    assert computed.decisions >= 2 and computed.returns > 0 and computed.fund_profiles > 0
    session.expire_all()

    monkeypatch.setattr(common, "now_et", lambda: datetime(2026, 9, 29, 18, tzinfo=ET))
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    owner = manifest["form4_buy_single"]["expect"]["owner_ciks"][0]
    with TestClient(app) as client:
        header = client.get(f"/api/insiders/{owner}")
        assert header.status_code == 200
        assert header.json()["n_decisions"] >= 1
        feed = client.get("/api/feed", params={"include_10b5_1": "true"})
        assert feed.status_code == 200
        assert {item["accession_no"] for item in feed.json()["items"]} >= {
            manifest[k]["accession"] for k in KEYS
        }
        for basis in ("filed", "executed"):
            perf = client.get(f"/api/insiders/{owner}/performance", params={"basis": basis})
            assert perf.status_code == 200
            assert perf.json()["points"][0]["nav"] == pytest.approx(1.0)
            fund = client.get(f"/api/funds/{fund_cik}/performance", params={"basis": basis})
            assert fund.status_code == 200
            assert fund.json()["points"][0]["nav"] == pytest.approx(1.0)
        compared = client.get("/api/compare", params={"ids": f"insider:{owner},fund:{fund_cik}"})
        assert compared.status_code == 200
        assert len(compared.json()["profiles"]) == 2

    counts = [
        session.scalar(select(func.count()).select_from(model))
        for model in (InsiderTransaction, FundPosition)
    ]
    for key in KEYS:
        outcome = ingest_raw(
            session,
            fixture_bytes(key),
            source="test",
            raw_path=None,
            first_seen_at=None,
            settings=settings,
            archive=tmp_archive,
        )
        assert outcome.status == "parsed"
    session.commit()
    repeated = run_full(session_factory, as_of=AS_OF)
    assert repeated.decisions == computed.decisions
    assert repeated.returns == computed.returns
    assert [
        session.scalar(select(func.count()).select_from(model))
        for model in (InsiderTransaction, FundPosition)
    ] == counts
