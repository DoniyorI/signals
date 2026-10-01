"""Reference and price jobs: registration, backfill_reference, and prices_daily."""

import json
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO

import pandas as pd
from sqlalchemy import select

import signals.prices.jobs as price_jobs
import signals.reference.jobs as reference_jobs
from signals.db.models import FilingAcceptance, Issuer, PriceDaily
from signals.domain.calendars import ET
from signals.domain.types import BENCHMARK_SYMBOLS
from signals.jobs import JOBS, JobContext, load_all_jobs
from signals.reference.shares import frames_url
from signals.sec.client import SecClient
from tests.support import MockRouter

BARS_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume", "adj_close")


def _ctx(settings, session_factory, sec, archive, *, now=None) -> JobContext:
    kwargs = {} if now is None else {"now": now}
    return JobContext(
        settings=settings,
        session_factory=session_factory,
        sec=sec,
        archive=archive,
        request_id=None,
        params={},
        progress={},
        save_progress=lambda p: None,
        **kwargs,
    )


def test_jobs_registered():
    load_all_jobs()
    assert JOBS["backfill_reference"].cron is None
    assert JOBS["reference_refresh"].cron == {"day_of_week": "sun", "hour": 4, "minute": 0}
    assert JOBS["tickers_refresh"].cron == {"hour": 5, "minute": 0}
    assert JOBS["backfill_prices"].cron is None
    assert JOBS["prices_daily"].cron == {"day_of_week": "mon-fri", "hour": 18, "minute": 30}


def _acme_submission_json() -> bytes:
    return json.dumps(
        {
            "cik": "1000001",
            "name": "Acme Corp",
            "sic": "3571",
            "sicDescription": "Electronic Computers",
            "tickers": ["ACME"],
            "exchanges": ["Nasdaq"],
            "filings": {
                "recent": {
                    "accessionNumber": [],
                    "form": [],
                    "filingDate": [],
                    "acceptanceDateTime": [],
                },
                "files": [],
            },
        }
    ).encode()


def _small_submissions_zip(fixture_bytes, manifest) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        owner_cik = manifest["submissions_owner"]["cik"]
        zf.writestr(f"CIK{owner_cik:010d}.json", fixture_bytes("submissions_owner"))
        zf.writestr("CIK0001000001.json", _acme_submission_json())
    return buf.getvalue()


def test_backfill_reference_with_mocks(
    session, session_factory, settings, tmp_archive, fixture_bytes, manifest, monkeypatch
):
    monkeypatch.setattr(reference_jobs, "_frame_quarters", lambda *a, **k: [(2016, 1), (2016, 2)])

    router = MockRouter(
        {
            reference_jobs.SUBMISSIONS_URL: _small_submissions_zip(fixture_bytes, manifest),
            reference_jobs.COMPANY_TICKERS_URL: fixture_bytes("company_tickers_exchange"),
            frames_url(2016, 1): 404,
            frames_url(2016, 2): fixture_bytes("frames_sample"),
        }
    )
    sec = SecClient(settings, http=router.client, archive=tmp_archive, sleep=lambda s: None)
    ctx = _ctx(settings, session_factory, sec, tmp_archive)

    result = reference_jobs.backfill_reference(ctx)

    acc = manifest["submissions_owner"]["expect"]["accession"]
    assert session.get(FilingAcceptance, acc) is not None

    ticker_cik = manifest["company_tickers_exchange"]["expect"]["fixture_issuer_rows"][0][0]
    assert session.get(Issuer, ticker_cik) is not None  # issuers exist (from company_tickers)

    acme = session.get(Issuer, 1000001)
    assert acme is not None and acme.sector == "Technology"  # sectors are assigned
    assert isinstance(result, dict)


def test_backfill_reference_is_resumable(
    session, session_factory, settings, tmp_archive, fixture_bytes, manifest, monkeypatch
):
    """A second call with the same (empty) progress dict re-does the work, but a call that
    resumes from a saved progress dict skips units already marked done -- no re-fetch."""
    monkeypatch.setattr(reference_jobs, "_frame_quarters", lambda *a, **k: [(2016, 1)])

    router = MockRouter(
        {
            reference_jobs.SUBMISSIONS_URL: _small_submissions_zip(fixture_bytes, manifest),
            reference_jobs.COMPANY_TICKERS_URL: fixture_bytes("company_tickers_exchange"),
            frames_url(2016, 1): fixture_bytes("frames_sample"),
        }
    )
    sec = SecClient(settings, http=router.client, archive=tmp_archive, sleep=lambda s: None)

    progress: dict = {}
    ctx = JobContext(
        settings=settings,
        session_factory=session_factory,
        sec=sec,
        archive=tmp_archive,
        request_id=None,
        params={},
        progress=progress,
        save_progress=progress.update,
    )
    reference_jobs.backfill_reference(ctx)
    assert "submissions" in progress["done"]
    n_requests_first_run = len(router.requests)

    # Resume: same progress dict (all units already marked done) -> no new HTTP calls.
    ctx2 = JobContext(
        settings=settings,
        session_factory=session_factory,
        sec=sec,
        archive=tmp_archive,
        request_id=None,
        params={},
        progress=dict(progress),
        save_progress=progress.update,
    )
    reference_jobs.backfill_reference(ctx2)
    assert len(router.requests) == n_requests_first_run  # nothing re-fetched


@dataclass
class FakeCall:
    symbols: list[str]
    start: date
    end: date


@dataclass
class FakePriceProvider:
    name: str
    bars: dict[str, list[dict]] = field(default_factory=dict)
    calls: list[FakeCall] = field(default_factory=list)

    def daily_bars(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
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


def test_prices_daily_uses_providers(session, session_factory, settings, tmp_archive, monkeypatch):
    fake_primary = FakePriceProvider(
        name="fake_primary",
        bars={sym: [_bar(date(2024, 1, 2), 100.0)] for sym in BENCHMARK_SYMBOLS},
    )
    monkeypatch.setattr(
        price_jobs, "make_providers", lambda settings, http=None: (fake_primary, None)
    )

    sec = SecClient(settings, http=MockRouter({}).client, sleep=lambda s: None)
    ctx = _ctx(
        settings,
        session_factory,
        sec,
        tmp_archive,
        now=lambda: datetime(2024, 1, 3, 12, 0, tzinfo=ET),  # a Wednesday: a trading day
    )

    result = price_jobs.prices_daily(ctx)

    stored = session.scalars(
        select(PriceDaily).where(PriceDaily.symbol.in_(BENCHMARK_SYMBOLS))
    ).all()
    assert len(stored) == len(BENCHMARK_SYMBOLS)
    assert {p.symbol for p in stored} == set(BENCHMARK_SYMBOLS)
    assert all(p.source == "fake_primary" for p in stored)
    assert isinstance(result, dict)


def test_prices_daily_fills_all_missed_trading_days_incrementally(
    session, session_factory, settings, tmp_archive, monkeypatch
):
    from signals.domain.calendars import trading_days
    from signals.prices.universe import UniverseEntry
    from tests.factories import make_prices
    from tests.integration.test_price_loader import FakeProvider, _bar

    start, end = date(2026, 9, 18), date(2026, 9, 30)
    make_prices(session, "GAP", start, [10.0])
    expected = trading_days(start, end)
    provider = FakeProvider("catchup_prices", {"GAP": [_bar(day, 10.0) for day in expected]})
    monkeypatch.setattr(
        price_jobs, "build_price_universe", lambda s, **kwargs: [UniverseEntry("GAP", start)]
    )
    monkeypatch.setattr(price_jobs, "make_providers", lambda settings: (provider, None))
    ctx = _ctx(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        now=lambda: datetime(2026, 9, 30, 19, tzinfo=ET),
    )
    price_jobs.prices_daily(ctx)
    stored = list(
        session.scalars(
            select(PriceDaily.date).where(PriceDaily.symbol == "GAP").order_by(PriceDaily.date)
        )
    )
    assert stored == expected
    assert provider.calls[0].start == start and provider.calls[-1].end == end
