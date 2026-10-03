from datetime import date, datetime

from sqlalchemy import select

from signals.analytics import curves, run
from signals.db.models import Decision, DecisionOwner, ProfileStats, Ticker
from signals.domain.appstate import get_state, set_state
from signals.domain.calendars import ET, trading_days
from signals.domain.types import BENCHMARK_SYMBOLS
from signals.jobs import JobContext
from signals.prices import jobs as price_jobs
from signals.prices import universe
from signals.sec.client import SecClient
from tests.factories import make_filing, make_issuer, make_owner, make_transaction
from tests.integration.test_analytics_run import AS_OF, seeded_world
from tests.integration.test_jobs_reference_prices import FakePriceProvider, _bar
from tests.support import MockRouter


def test_profile_universe_includes_joint_owner_and_dated_symbols_only(session):
    make_issuer(session, ticker="NEW", ticker_from=date(2020, 1, 1))
    make_issuer(session, cik=1000002, ticker="OTHER")
    make_owner(session)
    make_owner(session, cik=2000002)
    make_filing(session, owners=(2000001, 2000002))
    make_transaction(session, accession_no="0002000001-24-000001", owner_ciks=(2000001, 2000002))
    session.add(
        Ticker(
            issuer_cik=1000001,
            symbol="OLD",
            valid_from=date(2010, 1, 1),
            valid_to=date(2019, 12, 31),
            source="test",
        )
    )
    session.flush()
    result = universe.build_insider_price_universe(
        session, owner_cik=2000002, backfill_start=date(2016, 1, 1), as_of=date(2024, 12, 31)
    )
    assert {e.symbol for e in result} == {"NEW", "OLD", *BENCHMARK_SYMBOLS}
    assert next(e.start for e in result if e.symbol == "OLD") == date(2015, 9, 3)


def test_profile_analytics_preserves_other_owners_decision_ids(session, session_factory):
    seeded_world(session)
    run.run_full(session_factory, as_of=AS_OF, include_funds=False)
    other = set(
        session.scalars(select(DecisionOwner.decision_id).where(DecisionOwner.owner_cik == 2000002))
    )
    result = run.run_insider_profile(session_factory, owner_cik=2000001, as_of=AS_OF)
    assert result.decisions == 2 and result.insider_profiles == 4
    assert (
        set(
            session.scalars(
                select(DecisionOwner.decision_id).where(DecisionOwner.owner_cik == 2000002)
            )
        )
        == other
    )
    assert len(list(session.scalars(select(Decision)))) == 4
    for basis in ("filed", "executed"):
        curves._curve_slots.cache_clear()
        assert not curves.insider_curve(
            session, 2000001, basis=basis, include_10b5_1=False, as_of=AS_OF
        ).points.empty


def test_scoped_job_loads_prices_before_analytics_without_marking_full_backfill_complete(
    session, session_factory, settings, tmp_archive, monkeypatch
):
    make_issuer(session)
    make_filing(session)
    make_transaction(session, accession_no="0002000001-24-000001")
    days = trading_days(date(2024, 1, 2), AS_OF)
    provider = FakePriceProvider(
        "recorded",
        {
            symbol: [_bar(day, 100 + i / 10) for i, day in enumerate(days)]
            for symbol in ("ACME", *BENCHMARK_SYMBOLS)
        },
    )
    monkeypatch.setattr(price_jobs, "make_providers", lambda settings: (provider, None))
    set_state(session, "prices_last", {"requested": 10000, "loaded": 0})
    checkpoints = []
    ctx = JobContext(
        settings,
        session_factory,
        SecClient(settings, http=MockRouter({}).client),
        tmp_archive,
        None,
        {"owner_cik": 2000001},
        {},
        lambda p: checkpoints.append(dict(p)),
        lambda: datetime(2024, 12, 31, 19, tzinfo=ET),
    )
    result = price_jobs.refresh_insider_performance(ctx)
    assert result["owner_cik"] == 2000001
    assert ctx.progress["stage"] == "done"
    assert ctx.progress["symbols_done"] == ctx.progress["symbols_total"] == 14
    assert any(p["stage"] == "prices" for p in checkpoints)
    assert any(p["stage"] == "analytics" for p in checkpoints)
    assert get_state(session, "prices_last") == {"requested": 10000, "loaded": 0}
    session.expire_all()
    assert session.get(ProfileStats, ("insider", 2000001, "filed", False)).n_complete == 1
    assert get_state(session, "analytics_version") is not None
