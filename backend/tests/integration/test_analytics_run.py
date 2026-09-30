"""Full and incremental analytics runs, the curve service and the analytics jobs."""

from collections.abc import Sequence
from dataclasses import asdict
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError

import signals.analytics.jobs  # noqa: F401  (registers the analytics jobs)
from signals.analytics import curves, run
from signals.analytics.run import RunResult, refresh_feed_items, run_full, run_incremental
from signals.db.models import (
    Decision,
    DecisionReturn,
    FeedItem,
    FundNavDaily,
    IngestRun,
    InsiderTransaction,
    JobRequest,
    OwnerRole,
    Position,
    ProfileStats,
    ProfileWindow,
)
from signals.domain.appstate import get_state, set_state
from signals.domain.calendars import ET, trading_days
from signals.domain.feed import FeedItemIn, upsert_feed_item
from signals.jobs import JOBS, claim_next_request, make_ctx_builder, request_job, run_request
from signals.sec.client import SecClient
from tests.factories import (
    make_filing,
    make_fund_filing,
    make_fund_manager,
    make_fund_position,
    make_issuer,
    make_prices,
    make_security,
    make_transaction,
)
from tests.support import MockRouter

AS_OF = date(2024, 12, 31)
FIRST_DAY = date(2023, 1, 3)
BUYS = {2000001: date(2024, 2, 1), 2000002: date(2024, 2, 6), 2000003: date(2024, 2, 12)}
SALE = date(2024, 8, 1)
FUND = 3000001


@pytest.fixture(autouse=True)
def fund_changes(monkeypatch) -> list[object]:
    """Workstream B's compute_fund_changes is not on this branch: record the calls instead."""
    calls: list[object] = []

    def record(session) -> int:
        calls.append(session)
        return 0

    monkeypatch.setattr(run, "_fund_changes", record)
    return calls


@pytest.fixture(autouse=True)
def fresh_curve_cache():
    """Cached curves are keyed by the analytics run; tests reuse CIKs across worlds."""
    curves._curve_slots.cache_clear()
    yield
    curves._curve_slots.cache_clear()


def _rising(n: int, start: float) -> list[float]:
    return [start * 1.001**i for i in range(n)]


def _accepted(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 16, 30, tzinfo=ET)


def insider_trade(
    session, owner: int, issuer_cik: int, day: date, *, code: str = "P", number: int = 1
) -> str:
    """A Form 4 filed the next day at 16:30 ET, with its feed item."""
    acc = f"{owner:010d}-24-{number:06d}"
    filed = day + timedelta(days=1)
    make_filing(
        session,
        accession_no=acc,
        issuer_cik=issuer_cik,
        filed_date=filed,
        accepted_at=_accepted(filed),
        owners=(owner,),
    )
    make_transaction(
        session,
        accession_no=acc,
        issuer_cik=issuer_cik,
        owner_ciks=(owner,),
        code=code,
        transaction_date=day,
        shares=1000.0 if code == "P" else 11000.0,
        shares_owned_after=11000.0 if code == "P" else 0.0,
    )
    upsert_feed_item(
        session,
        FeedItemIn(
            accession_no=acc,
            form_type="4",
            accepted_at=_accepted(filed),
            filed_date=filed,
            issuer_cik=issuer_cik,
            owner_group=str(owner),
            owner_ciks=(owner,),
            direction="buy" if code == "P" else "sell",
            codes=(code,),
        ),
    )
    return acc


def seeded_world(session, *, benchmarks: Sequence[str] = ("SPY", "QQQ", "XLK")) -> None:
    """ACME (Technology) rising 0.1% a day over 2023-2024 with SPY, QQQ and XLK; three owners
    buying in February 2024 (g1 is the CEO), g1 selling in August; one tracked fund with two
    reported periods holding ACME."""
    make_issuer(session)
    n = len(trading_days(FIRST_DAY, AS_OF))
    make_prices(session, "ACME", FIRST_DAY, _rising(n, 10.0))
    for symbol in benchmarks:
        make_prices(session, symbol, FIRST_DAY, _rising(n, 100.0))
    for owner, day in BUYS.items():
        insider_trade(session, owner, 1000001, day)
    insider_trade(session, 2000001, 1000001, SALE, code="S", number=2)
    session.add(OwnerRole(owner_cik=2000001, issuer_cik=1000001, roles=["CEO"]))
    make_fund_manager(session, cik=FUND)
    make_security(session)
    for number, (period, filed) in enumerate(
        ((date(2023, 12, 31), date(2024, 2, 14)), (date(2024, 3, 31), date(2024, 5, 15))),
        start=1,
    ):
        acc = f"{FUND:010d}-24-{number:06d}"
        make_fund_filing(
            session,
            accession_no=acc,
            filer_cik=FUND,
            period=period,
            filed_date=filed,
            accepted_at=_accepted(filed),
        )
        make_fund_position(session, accession_no=acc, filer_cik=FUND, period=period)
    session.flush()


def _counts(result: RunResult) -> dict[str, object]:
    return {k: v for k, v in asdict(result).items() if k != "seconds"}


def _badges(session) -> dict[tuple[str, str, date], list[str]]:
    session.expire_all()
    return {
        (d.owner_group, d.direction, d.first_trade_date): list(d.badges)
        for d in session.scalars(select(Decision))
    }


def _count(session, model, *where) -> int:
    return int(session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def _returns_of(session, issuer_cik: int) -> set[tuple]:
    rows = session.execute(
        select(
            DecisionReturn.decision_id,
            DecisionReturn.basis,
            DecisionReturn.horizon,
            DecisionReturn.entry_date,
            DecisionReturn.exit_date,
            DecisionReturn.raw_return,
            DecisionReturn.is_complete,
        )
        .join(Decision, Decision.id == DecisionReturn.decision_id)
        .where(Decision.issuer_cik == issuer_cik)
    )
    return {tuple(r) for r in rows}


def _feed(session, accession_no: str) -> FeedItem:
    session.expire_all()
    item = session.get(FeedItem, accession_no)
    assert item is not None
    return item


# ----------------------------------------------------------------------------- full runs
def test_run_full_counts(session, session_factory, fund_changes):
    seeded_world(session)
    steps: list[str] = []

    result = run_full(session_factory, as_of=AS_OF, progress=steps.append)

    assert (result.decisions, result.returns, result.insider_profiles, result.fund_profiles) == (
        4,
        32,
        12,
        2,
    )
    badges = _badges(session)
    assert all("cluster_buy" in badges[(str(o), "buy", day)] for o, day in BUYS.items())
    assert "cluster_buy" not in badges[("2000001", "sell", SALE)]
    for owner in BUYS:
        assert _count(session, ProfileStats, ProfileStats.cik == owner) == 4
    assert _count(session, FundNavDaily, FundNavDaily.cik == FUND) > 0
    assert len(fund_changes) == 1 and steps[0] == "positions" and "funds" in steps
    position = session.get(Position, (2000002, 1000001, "", "D"))
    assert position is not None and position.shares == 11000.0

    last_close = _rising(len(trading_days(FIRST_DAY, AS_OF)), 10.0)[-1]
    for owner in BUYS:
        item = _feed(session, f"{owner:010d}-24-000001")
        assert "cluster_buy" in item.badges and item.sector == "Technology"
        assert item.market_cap_usd == pytest.approx(1e9 * last_close)
    state = get_state(session, "analytics_version")
    assert state is not None and state["as_of"] == AS_OF.isoformat() and state["run_at"]


def test_run_full_idempotent(session, session_factory):
    seeded_world(session)
    first = run_full(session_factory, as_of=AS_OF)
    badges = _badges(session)

    second = run_full(session_factory, as_of=AS_OF)

    assert _counts(second) == _counts(first)
    assert _badges(session) == badges


def test_run_full_without_funds(session, session_factory, fund_changes):
    seeded_world(session)
    steps: list[str] = []
    result = run_full(session_factory, as_of=AS_OF, include_funds=False, progress=steps.append)
    assert result.fund_profiles == 0 and fund_changes == [] and "funds" not in steps
    assert _count(session, FundNavDaily) == 0


# ----------------------------------------------------------------------------- incremental
def test_incremental_only_touches_given_issuers(session, session_factory):
    seeded_world(session)
    run_full(session_factory, as_of=AS_OF)
    before = _returns_of(session, 1000001)
    make_issuer(session, cik=1000002, name="Beta Corp", ticker="BETA")
    make_prices(session, "BETA", FIRST_DAY, _rising(len(trading_days(FIRST_DAY, AS_OF)), 20.0))
    acc = insider_trade(session, 2000009, 1000002, date(2024, 3, 7))

    result = run_incremental(
        session_factory, issuer_ciks=[1000002], owner_ciks=[2000009], as_of=AS_OF
    )

    assert (result.decisions, result.returns, result.fund_profiles) == (1, 8, 0)
    assert _returns_of(session, 1000001) == before
    assert len(_returns_of(session, 1000002)) == 8
    assert _count(session, ProfileStats, ProfileStats.cik == 2000009) == 4
    assert _count(session, ProfileStats, ProfileStats.cik == 2000002) == 4
    assert "first_buy_2y" in _feed(session, acc).badges


def test_incremental_refreshes_owners_of_rebuilt_and_removed_decisions(session, session_factory):
    seeded_world(session)
    run_full(session_factory, as_of=AS_OF)
    g3_buy = session.scalars(
        select(InsiderTransaction).where(InsiderTransaction.owner_group == "2000003")
    ).one()
    g3_buy.superseded_by = "0002000003-24-000099"
    session.flush()

    run_incremental(session_factory, issuer_ciks=[1000001], owner_ciks=[], as_of=AS_OF)

    session.expire_all()
    assert _count(session, ProfileStats, ProfileStats.cik == 2000003) == 0
    referenced = {
        i
        for s in session.scalars(select(ProfileStats))
        for i in (s.best_decision_id, s.worst_decision_id)
        if i is not None
    }
    assert referenced and referenced <= set(session.scalars(select(Decision.id)))


def test_incremental_with_empty_scope_changes_nothing(session, session_factory):
    seeded_world(session)
    run_full(session_factory, as_of=AS_OF)
    ids = sorted(session.scalars(select(Decision.id)))
    version = get_state(session, "analytics_version")

    result = run_incremental(session_factory, issuer_ciks=[], owner_ciks=[], as_of=AS_OF)

    assert _counts(result) == {
        "decisions": 0,
        "returns": 0,
        "badges": 0,
        "insider_profiles": 0,
        "fund_profiles": 0,
    }
    assert sorted(session.scalars(select(Decision.id))) == ids
    assert _count(session, Position) == 3
    assert get_state(session, "analytics_version") == version


def test_runs_wait_for_the_analytics_lock(session, session_factory, db_engine):
    seeded_world(session)
    with db_engine.connect() as other:
        other.execute(text("SELECT pg_advisory_lock(:key)"), {"key": run.ANALYTICS_LOCK_KEY})
        try:
            session.execute(text("SET lock_timeout = '200ms'"))
            with pytest.raises(OperationalError, match="lock timeout"):
                run_incremental(session_factory, issuer_ciks=[1000001], owner_ciks=[], as_of=AS_OF)
        finally:
            other.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": run.ANALYTICS_LOCK_KEY})
    assert _count(session, Decision) == 0  # nothing ran


# ----------------------------------------------------------------------------- feed refresh
def test_feed_refresh_clears_stale_badges_and_prices_market_cap(session):
    make_issuer(session)  # 1e9 shares, Technology
    make_issuer(session, cik=1000002, name="Gone Corp", ticker="GONE", sector=None)
    days = trading_days(FIRST_DAY, AS_OF)
    make_prices(session, "ACME", FIRST_DAY, [10.0] * (len(days) - 1) + [12.0])
    make_prices(session, "GONE", FIRST_DAY, [5.0] * 300)  # no bar in the last weeks
    for acc, issuer_cik in (("0002000001-24-000001", 1000001), ("0002000001-24-000002", 1000002)):
        upsert_feed_item(
            session,
            FeedItemIn(
                accession_no=acc,
                form_type="4",
                issuer_cik=issuer_cik,
                badges=("late_filing",),
                sector="Energy",
                market_cap_usd=1.0,
            ),
        )

    refresh_feed_items(session, as_of=AS_OF)

    acme, gone = _feed(session, "0002000001-24-000001"), _feed(session, "0002000001-24-000002")
    assert (acme.badges, acme.sector, acme.market_cap_usd) == ([], "Technology", 12e9)
    assert (gone.badges, gone.sector, gone.market_cap_usd) == ([], None, None)


# ----------------------------------------------------------------------------- curves
def test_insider_curve_normalized(session, session_factory):
    seeded_world(session)
    run_full(session_factory, as_of=AS_OF)

    curve = curves.insider_curve(session, 2000001, basis="filed", include_10b5_1=False, as_of=AS_OF)

    assert list(curve.points.columns) == ["nav", "spy", "qqq", "sector"]
    assert curve.points.iloc[0].tolist() == [1.0, 1.0, 1.0, 1.0]
    assert curve.points.index[0] == date(2024, 2, 5)  # the first buy's filed entry
    assert len(curve.windows) == 4 and curve.coverage_pct is None and curve.basis == "filed"
    assert curve.points["nav"].iloc[-1] > 1.0


def test_insider_curve_without_decisions_is_empty(session):
    curve = curves.insider_curve(
        session, 2999999, basis="executed", include_10b5_1=True, as_of=AS_OF
    )
    assert curve.points.empty and list(curve.points.columns) == ["nav", "spy", "qqq", "sector"]
    assert [w.window for w in curve.windows] == ["ytd", "1y", "3y", "5y"]
    assert all(
        value is None for w in curve.windows for key, value in asdict(w).items() if key != "window"
    )


def test_insider_curve_cached_until_the_next_run(session, session_factory):
    seeded_world(session)
    run_full(session_factory, as_of=AS_OF)
    first = curves.insider_curve(session, 2000002, basis="filed", include_10b5_1=False, as_of=AS_OF)
    session.execute(delete(DecisionReturn))  # the entries behind the curve disappear

    cached = curves.insider_curve(
        session, 2000002, basis="filed", include_10b5_1=False, as_of=AS_OF
    )
    set_state(session, "analytics_version", {"as_of": AS_OF.isoformat(), "run_at": "later"})
    fresh = curves.insider_curve(session, 2000002, basis="filed", include_10b5_1=False, as_of=AS_OF)

    assert cached.points.equals(first.points) and not cached.points.empty
    assert fresh.points.empty


def test_fund_curve_reads_the_stored_curve_and_windows(session, session_factory):
    seeded_world(session)
    run_full(session_factory, as_of=AS_OF)
    rows = session.scalars(
        select(FundNavDaily)
        .where(FundNavDaily.cik == FUND, FundNavDaily.basis == "executed")
        .order_by(FundNavDaily.date)
    ).all()
    ytd = session.get(ProfileWindow, ("fund", FUND, "executed", False, "ytd"))
    assert ytd is not None and ytd.ret is not None

    curve = curves.fund_curve(session, FUND, basis="executed", as_of=AS_OF)

    assert list(curve.points.index) == [r.date for r in rows]
    assert curve.points.iloc[0].tolist() == [1.0, 1.0, 1.0, 1.0]
    assert curve.points["nav"].iloc[-1] == pytest.approx(rows[-1].nav / rows[0].nav)
    assert curve.coverage_pct == rows[-1].coverage
    assert [w.window for w in curve.windows] == ["ytd", "1y", "3y", "5y"]
    assert curve.windows[0].ret == pytest.approx(ytd.ret)

    earlier = curves.fund_curve(session, FUND, basis="executed", as_of=date(2024, 6, 28))
    assert earlier.points.index[-1] == date(2024, 6, 28)


def test_fund_curve_untracked_raises(session):
    make_fund_manager(session, cik=3000009, is_tracked=False)
    with pytest.raises(LookupError, match="fund not tracked"):
        curves.fund_curve(session, 3000009, basis="filed", as_of=AS_OF)
    with pytest.raises(LookupError):
        curves.fund_curve(session, 3999999, basis="filed", as_of=AS_OF)


def test_curve_points_fill_a_benchmark_without_prices(session, session_factory):
    seeded_world(session, benchmarks=("SPY", "XLK"))  # no QQQ bars at all
    run_full(session_factory, as_of=AS_OF)

    insider = curves.insider_curve(
        session, 2000001, basis="filed", include_10b5_1=False, as_of=AS_OF
    )
    fund = curves.fund_curve(session, FUND, basis="executed", as_of=AS_OF)

    for curve in (insider, fund):
        assert not curve.points.empty and curve.points["qqq"].eq(1.0).all()
        assert curve.points["spy"].iloc[-1] > 1.0
    assert fund.windows[0].ret_qqq is None


# ----------------------------------------------------------------------------- jobs
def test_jobs_registered():
    assert JOBS["analytics_full"].cron == {"hour": 2, "minute": 0}
    assert "analytics_incremental" in JOBS and JOBS["analytics_incremental"].cron is None


def test_incremental_job_runs_the_requested_scope(session, session_factory, settings, tmp_archive):
    seeded_world(session)
    rid = request_job(
        session, "analytics_incremental", {"issuer_ciks": [1000001], "owner_ciks": [2000001]}
    )
    claimed = claim_next_request(session)
    assert claimed is not None and claimed.id == rid
    session.flush()
    sec = SecClient(settings, http=MockRouter({}).client, sleep=lambda s: None)

    run_request(make_ctx_builder(settings, session_factory, sec, tmp_archive), session_factory, rid)

    session.expire_all()
    req = session.get(JobRequest, rid)
    assert req is not None and (req.status, req.error) == ("done", None)
    assert req.progress["result"]["decisions"] == 4
    assert _count(session, Decision, Decision.issuer_cik == 1000001) == 4
    assert _count(session, IngestRun, IngestRun.job == "analytics_incremental") == 1
