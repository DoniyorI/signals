"""Production price jobs keep adjusted history current and bound cold-load work."""

from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import func, select

import signals.prices.jobs as price_jobs
from signals.db.models import PriceDaily
from signals.domain.calendars import ET
from signals.jobs import JobContext
from signals.prices.loader import _upsert_bars, load_prices
from signals.prices.universe import UniverseEntry
from signals.sec.client import SecClient
from tests.integration.test_price_loader import FakeProvider, _bar
from tests.support import MockRouter


def _prices(session, symbol="ACME"):
    session.expire_all()
    return list(
        session.scalars(
            select(PriceDaily).where(PriceDaily.symbol == symbol).order_by(PriceDaily.date)
        )
    )


def test_large_price_upsert_stores_and_updates_8000_bars(session):
    rows = [
        {"symbol": "BULK", **_bar(date(2000, 1, 1) + timedelta(days=i), 100.0)} for i in range(8000)
    ]
    assert _upsert_bars(session, pd.DataFrame(rows), "first") == 8000
    rows[0]["adj_close"] = 50.0
    _upsert_bars(session, pd.DataFrame(rows), "second")
    assert session.scalar(select(func.count()).select_from(PriceDaily)) == 8000
    assert (
        session.get(PriceDaily, ("BULK", date(2000, 1, 1)), populate_existing=True).adj_close
        == 50.0
    )


@pytest.mark.parametrize("job_name", ["prices_daily", "backfill_prices"])
@pytest.mark.parametrize(
    "adjusted, new_close", [(50.0, 50.0), (99.0, 99.0)], ids=["split", "dividend"]
)
def test_jobs_refresh_old_adjusted_prices(
    session, session_factory, settings, tmp_archive, monkeypatch, job_name, adjusted, new_close
):
    primary = FakeProvider(
        "vendor", bars={"ACME": [_bar(date(2024, 1, 2), 100.0), _bar(date(2024, 1, 3), 100.0)]}
    )
    universe = [UniverseEntry("ACME", date(2024, 1, 2))]
    monkeypatch.setattr(price_jobs, "build_price_universe", lambda *a, **k: universe)
    monkeypatch.setattr(price_jobs, "make_providers", lambda *a, **k: (primary, None))
    now = datetime(2024, 1, 3 if job_name == "prices_daily" else 4, 19, tzinfo=ET)
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client, sleep=lambda _: None),
        tmp_archive,
        None,
        {},
        {},
        lambda p: None,
        now=lambda: now,
    )
    job = getattr(price_jobs, job_name)
    job(ctx)
    assert [row.adj_close for row in _prices(session)] == [100.0, 100.0]
    primary.bars["ACME"] = [
        {**_bar(date(2024, 1, 2), 100.0), "adj_close": adjusted},
        {**_bar(date(2024, 1, 3), 100.0), "adj_close": adjusted},
        _bar(date(2024, 1, 4), new_close),
    ]
    now += timedelta(days=1)
    job(ctx)
    stored = _prices(session)
    assert [row.adj_close for row in stored] == [adjusted, adjusted, new_close]
    assert stored[-1].adj_close / stored[0].adj_close - 1 == pytest.approx(0.0)
    calls_before = len(primary.calls)
    result = job(ctx)
    assert result["rows"] == 0
    assert len(primary.calls) > calls_before
    assert len(_prices(session)) == 3


def test_same_end_rerun_detects_adjustment_change(session, session_factory):
    provider = FakeProvider(
        "vendor", bars={"ACME": [_bar(date(2024, 1, 2), 100.0), _bar(date(2024, 1, 3), 100.0)]}
    )
    universe = [UniverseEntry("ACME", date(2024, 1, 2))]
    load_prices(session_factory, provider, None, universe, end=date(2024, 1, 3))
    provider.bars["ACME"] = [{**bar, "adj_close": 50.0} for bar in provider.bars["ACME"]]
    load_prices(session_factory, provider, None, universe, end=date(2024, 1, 3))
    assert [row.adj_close for row in _prices(session)] == [50.0, 50.0]


def test_earlier_discovered_start_fills_previously_missing_history(session, session_factory):
    provider = FakeProvider(
        "vendor", bars={"ACME": [_bar(date(2024, 1, 2), 100.0), _bar(date(2024, 1, 3), 101.0)]}
    )
    load_prices(
        session_factory,
        provider,
        None,
        [UniverseEntry("ACME", date(2024, 1, 3))],
        end=date(2024, 1, 3),
    )
    load_prices(
        session_factory,
        provider,
        None,
        [UniverseEntry("ACME", date(2024, 1, 2))],
        end=date(2024, 1, 3),
    )
    assert [row.date for row in _prices(session)] == [date(2024, 1, 2), date(2024, 1, 3)]


def test_cold_load_bounds_provider_responses(session, session_factory):
    symbols = [f"S{i}" for i in range(80)]
    provider = FakeProvider(
        "vendor",
        bars={
            s: [_bar(date(2020, 1, 1) + timedelta(days=i), 100.0) for i in range(101)]
            for s in symbols
        },
    )
    result = load_prices(
        session_factory,
        provider,
        None,
        [UniverseEntry(s, date(2020, 1, 1)) for s in symbols],
        end=date(2024, 1, 1),
    )
    assert result.rows == 8080
    assert session.scalar(select(func.count()).select_from(PriceDaily)) == 8080
    assert all(
        len(call.symbols) <= 25 and (call.end - call.start).days < 366 for call in provider.calls
    )


def test_missing_prelisting_history_is_not_refetched_every_run(session_factory):
    provider = FakeProvider("vendor", bars={"IPO": [_bar(date(2024, 1, 3), 100.0)]})
    universe = [UniverseEntry("IPO", date(2020, 1, 1))]
    load_prices(session_factory, provider, None, universe, end=date(2024, 1, 3))
    provider.calls.clear()
    load_prices(session_factory, provider, None, universe, end=date(2024, 1, 3))
    assert len(provider.calls) == 1
    assert provider.calls[0].start == date(2024, 1, 3)


@pytest.mark.parametrize("job_name", ["prices_daily", "backfill_prices"])
def test_job_explicit_history_refresh_repairs_older_correction(
    session, session_factory, settings, tmp_archive, monkeypatch, job_name
):
    provider = FakeProvider(
        "vendor", bars={"ACME": [_bar(date(2024, 1, 2), 100.0), _bar(date(2024, 1, 3), 100.0)]}
    )
    universe = [UniverseEntry("ACME", date(2024, 1, 2))]
    load_prices(session_factory, provider, None, universe, end=date(2024, 1, 3))
    provider.bars["ACME"][0]["adj_close"] = 50.0  # latest sentinel is unchanged
    monkeypatch.setattr(price_jobs, "build_price_universe", lambda *a, **k: universe)
    monkeypatch.setattr(price_jobs, "make_providers", lambda *a, **k: (provider, None))
    now = datetime(2024, 1, 3 if job_name == "prices_daily" else 4, 19, tzinfo=ET)
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client, sleep=lambda _: None),
        tmp_archive,
        None,
        {"refresh_history": True},
        {},
        lambda p: None,
        now=lambda: now,
    )
    getattr(price_jobs, job_name)(ctx)
    assert [row.adj_close for row in _prices(session)] == [50.0, 100.0]


def test_failed_refresh_does_not_consume_adjustment_sentinel(session, session_factory):
    class FailingProvider(FakeProvider):
        fail = False

        def daily_bars(self, symbols, start, end):
            if self.fail and start.year == 2021:
                raise RuntimeError("vendor unavailable halfway through refresh")
            return super().daily_bars(symbols, start, end)

    provider = FailingProvider(
        "vendor", bars={"ACME": [_bar(date(2020, 1, 2), 100.0), _bar(date(2024, 1, 3), 100.0)]}
    )
    universe = [UniverseEntry("ACME", date(2020, 1, 2))]
    load_prices(session_factory, provider, None, universe, end=date(2024, 1, 3))
    provider.bars["ACME"] = [{**bar, "adj_close": 50.0} for bar in provider.bars["ACME"]]
    provider.fail = True
    with pytest.raises(RuntimeError, match="halfway through refresh"):
        load_prices(session_factory, provider, None, universe, end=date(2024, 1, 3))
    assert [row.adj_close for row in _prices(session)] == [100.0, 100.0]
    provider.fail = False
    load_prices(session_factory, provider, None, universe, end=date(2024, 1, 3))
    assert [row.adj_close for row in _prices(session)] == [50.0, 50.0]


def test_adjustment_refresh_does_not_reload_unaffected_symbol(session, session_factory):
    provider = FakeProvider(
        "vendor",
        bars={
            symbol: [_bar(date(2024, 1, 2), 100.0), _bar(date(2024, 1, 3), 100.0)]
            for symbol in ["ACME", "STABLE"]
        },
    )
    universe = [UniverseEntry(symbol, date(2024, 1, 2)) for symbol in provider.bars]
    load_prices(session_factory, provider, None, universe, end=date(2024, 1, 3))
    provider.bars["ACME"] = [{**bar, "adj_close": 50.0} for bar in provider.bars["ACME"]]
    provider.calls.clear()
    load_prices(session_factory, provider, None, universe, end=date(2024, 1, 3))
    assert [row.adj_close for row in _prices(session)] == [50.0, 50.0]
    assert [row.adj_close for row in _prices(session, "STABLE")] == [100.0, 100.0]
    assert all(
        "STABLE" not in call.symbols or call.start == date(2024, 1, 3) for call in provider.calls
    )


def test_fallback_provider_refreshes_adjusted_history(session, session_factory):
    primary = FakeProvider("primary")
    fallback = FakeProvider(
        "fallback", bars={"ACME": [_bar(date(2024, 1, 2), 100.0), _bar(date(2024, 1, 3), 100.0)]}
    )
    universe = [UniverseEntry("ACME", date(2024, 1, 2))]
    load_prices(session_factory, primary, fallback, universe, end=date(2024, 1, 3))
    fallback.bars["ACME"] = [{**bar, "adj_close": 50.0} for bar in fallback.bars["ACME"]]
    result = load_prices(session_factory, primary, fallback, universe, end=date(2024, 1, 3))
    assert result.fallback_used == ("ACME",)
    assert [row.adj_close for row in _prices(session)] == [50.0, 50.0]


@pytest.mark.parametrize("explicit", [False, True])
def test_incomplete_full_refresh_rolls_back_mixed_adjustments(session, session_factory, explicit):
    provider = FakeProvider(
        "vendor", bars={"ACME": [_bar(date(2024, 1, 2), 100.0), _bar(date(2024, 1, 3), 100.0)]}
    )
    universe = [UniverseEntry("ACME", date(2024, 1, 2))]
    load_prices(session_factory, provider, None, universe, end=date(2024, 1, 3))
    provider.bars["ACME"] = [{**_bar(date(2024, 1, 3), 100.0), "adj_close": 50.0}]
    if not explicit:
        universe = [UniverseEntry("ACME", date(2024, 1, 1))]
    with pytest.raises(RuntimeError, match="Incomplete adjusted-price refresh"):
        load_prices(
            session_factory,
            provider,
            None,
            universe,
            end=date(2024, 1, 3),
            refresh_history=explicit,
        )
    assert [row.adj_close for row in _prices(session)] == [100.0, 100.0]


def test_delisted_symbol_does_not_refetch_known_empty_tail(session_factory):
    provider = FakeProvider("vendor", bars={"OLD": [_bar(date(2020, 1, 2), 100.0)]})
    universe = [UniverseEntry("OLD", date(2020, 1, 2))]
    load_prices(session_factory, provider, None, universe, end=date(2024, 1, 3))
    provider.calls.clear()
    load_prices(session_factory, provider, None, universe, end=date(2024, 1, 4))
    assert [(call.start, call.end) for call in provider.calls] == [
        (date(2020, 1, 2), date(2020, 1, 2)),
        (date(2024, 1, 4), date(2024, 1, 4)),
    ]


def test_explicit_refresh_revisits_previously_empty_tail(session, session_factory):
    provider = FakeProvider("vendor", bars={"OLD": [_bar(date(2020, 1, 2), 100.0)]})
    universe = [UniverseEntry("OLD", date(2020, 1, 2))]
    load_prices(session_factory, provider, None, universe, end=date(2024, 1, 3))
    provider.bars["OLD"].append(_bar(date(2022, 1, 3), 101.0))
    load_prices(
        session_factory, provider, None, universe, end=date(2024, 1, 3), refresh_history=True
    )
    assert [row.date for row in _prices(session, "OLD")] == [date(2020, 1, 2), date(2022, 1, 3)]


def test_fallback_proportional_raw_and_adjusted_revision_refreshes_history(
    session, session_factory
):
    primary = FakeProvider("primary")
    fallback = FakeProvider(
        "fallback", bars={"ACME": [_bar(date(2024, 1, 2), 100.0), _bar(date(2024, 1, 3), 100.0)]}
    )
    universe = [UniverseEntry("ACME", date(2024, 1, 2))]
    load_prices(session_factory, primary, fallback, universe, end=date(2024, 1, 3))
    fallback.bars["ACME"] = [
        _bar(date(2024, 1, 2), 50.0),
        _bar(date(2024, 1, 3), 50.0),
        _bar(date(2024, 1, 4), 50.0),
    ]
    load_prices(session_factory, primary, fallback, universe, end=date(2024, 1, 4))
    stored = _prices(session)
    assert [row.close for row in stored] == [50.0, 50.0, 50.0]
    assert [row.adj_close for row in stored] == [50.0, 50.0, 50.0]
    assert stored[-1].adj_close / stored[0].adj_close - 1 == pytest.approx(0.0)
