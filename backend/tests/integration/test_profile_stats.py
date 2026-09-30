from collections.abc import Callable
from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from signals.analytics.decisions import build_decisions
from signals.analytics.returns import compute_decision_returns
from signals.analytics.stats import compute_fund_stats, compute_profile_stats, insider_nav
from signals.analytics.windows import window_stats
from signals.db.models import FundNavDaily, ProfileStats, ProfileWindow
from signals.domain.calendars import ET, trading_days
from tests.factories import (
    make_decision,
    make_decision_return,
    make_filing,
    make_fund_filing,
    make_fund_manager,
    make_fund_position,
    make_issuer,
    make_prices,
    make_security,
    make_transaction,
)

AS_OF = date(2025, 1, 2)


def _stats(session, cik: int, basis: str = "filed", include: bool = False, kind: str = "insider"):
    return session.get(ProfileStats, (kind, cik, basis, include))


def _window(session, cik: int, basis: str, window: str, kind: str = "insider") -> ProfileWindow:
    row = session.get(ProfileWindow, (kind, cik, basis, False, window))
    assert row is not None
    return row


def seed_owner_with_incomplete_decision(session) -> None:
    d = make_decision(session, first_trade_date=date(2024, 1, 12))
    make_decision_return(session, d.id, raw_return=0.25, excess_spy=0.2, is_complete=False)


def seed_mu_world(session) -> None:
    joint = make_decision(
        session, owner_ciks=(2000003, 2000004), first_trade_date=date(2024, 1, 10)
    )
    make_decision_return(session, joint.id, excess_spy=0.30)
    single = make_decision(session, owner_ciks=(2000001,), first_trade_date=date(2024, 1, 12))
    make_decision_return(session, single.id, excess_spy=0.0)


def test_rating_none_without_complete_decisions(session):
    seed_owner_with_incomplete_decision(session)  # one decision, 6m not complete yet
    compute_profile_stats(session, as_of=date(2024, 3, 1))
    ps = session.get(ProfileStats, ("insider", 2000001, "filed", False))
    assert (ps.n_complete, ps.rating, ps.confidence, ps.avg_roi_6m) == (0, None, None, None)
    assert ps.shrunk_mean is None and ps.n_decisions == 1


def test_population_mean_counts_joint_decision_once(session):
    # joint decision (owners 2000003 and 2000004) with excess 0.30 and a single-owner decision
    # (2000001) with 0.00
    seed_mu_world(session)
    compute_profile_stats(session, as_of=AS_OF)
    ps = session.get(ProfileStats, ("insider", 2000001, "filed", False))
    assert ps.shrunk_mean == pytest.approx((1 * 0.0 + 5 * 0.15) / 6)


def test_four_rows_per_insider(session):
    seed_mu_world(session)
    compute_profile_stats(session, as_of=AS_OF)
    n = session.scalar(
        select(func.count()).select_from(ProfileStats).where(ProfileStats.cik == 2000001)
    )
    assert n == 4  # {filed, executed} x include_10b5_1 {False, True}
    windows = session.scalar(
        select(func.count()).select_from(ProfileWindow).where(ProfileWindow.cik == 2000001)
    )
    assert windows == 16  # 4 windows for each of the 4 rows


def test_ratings_are_percentiles_among_rated_insiders(session):
    seed_mu_world(session)
    count = compute_profile_stats(session, as_of=AS_OF)
    assert count == 12
    ratings = {cik: _stats(session, cik).rating for cik in (2000001, 2000003, 2000004)}
    assert ratings == {2000001: 0, 2000003: 75, 2000004: 75}  # the joint owners tie
    assert _stats(session, 2000003).confidence == "low"
    assert _stats(session, 2000001, basis="executed").rating is None  # no executed returns


def test_toggle_leaves_out_planned_decisions_and_their_mean(session):
    disc = make_decision(session, owner_ciks=(2000001,), first_trade_date=date(2024, 1, 12))
    make_decision_return(session, disc.id, excess_spy=0.0)
    planned = make_decision(
        session, owner_ciks=(2000002,), first_trade_date=date(2024, 1, 12), plan_10b5_1="flag"
    )
    make_decision_return(session, planned.id, excess_spy=0.6)

    compute_profile_stats(session, as_of=AS_OF)

    assert _stats(session, 2000001).shrunk_mean == pytest.approx(0.0)
    assert _stats(session, 2000001, include=True).shrunk_mean == pytest.approx(5 * 0.3 / 6)
    off, on = _stats(session, 2000002), _stats(session, 2000002, include=True)
    assert (off.n_decisions, off.n_complete, off.rating) == (0, 0, None)
    assert (on.n_decisions, on.n_complete, on.avg_roi_6m) == (1, 1, pytest.approx(0.6))


def test_scoped_run_refreshes_every_rating(session):
    seed_mu_world(session)
    compute_profile_stats(session, as_of=AS_OF)
    new = make_decision(session, owner_ciks=(2000005,), first_trade_date=date(2024, 1, 15))
    make_decision_return(session, new.id, excess_spy=1.0)

    assert compute_profile_stats(session, owner_ciks=[2000005], as_of=AS_OF) == 4

    mu = (0.30 + 0.0 + 1.0) / 3
    assert _stats(session, 2000001).shrunk_mean == pytest.approx(5 * mu / 6)
    ratings = {cik: _stats(session, cik).rating for cik in (2000001, 2000003, 2000005)}
    assert ratings == {2000001: 0, 2000003: 50, 2000005: 100}
    assert session.scalar(select(func.count()).select_from(ProfileStats)) == 16


# ------------------------------------------------------------------ copycat-backed windows
CC_AS_OF = date(2024, 3, 1)


def _trading_world(session) -> None:
    make_issuer(session)  # ACME, Technology
    days = trading_days(date(2023, 10, 2), CC_AS_OF)
    make_prices(session, "ACME", days[0], [10.0 if i % 2 == 0 else 10.5 for i in range(len(days))])
    for symbol in ("SPY", "QQQ", "XLK"):
        make_prices(session, symbol, days[0], [100.0] * len(days))
    buy = make_filing(
        session,
        accession_no="0002000001-23-000001",
        filed_date=date(2023, 11, 2),
        accepted_at=datetime(2023, 11, 2, 16, 30, tzinfo=ET),
    )
    make_transaction(
        session,
        accession_no=buy.accession_no,
        transaction_date=date(2023, 11, 1),
        shares=1000.0,
        price=10.0,
        shares_owned_after=11000.0,
    )
    sell = make_filing(
        session,
        accession_no="0002000001-24-000002",
        filed_date=date(2024, 1, 17),
        accepted_at=datetime(2024, 1, 17, 16, 30, tzinfo=ET),
    )
    make_transaction(
        session,
        accession_no=sell.accession_no,
        code="S",
        transaction_date=date(2024, 1, 16),
        shares=11000.0,
        price=10.5,
        shares_owned_after=0.0,
    )
    build_decisions(session)
    compute_decision_returns(session, as_of=CC_AS_OF)


def test_copycat_windows_risk_and_identity(session):
    _trading_world(session)
    compute_profile_stats(session, as_of=CC_AS_OF)

    ps = _stats(session, 2000001)
    assert (ps.n_decisions, ps.n_buys, ps.n_sells, ps.n_complete) == (2, 1, 1, 0)
    assert (ps.primary_issuer_cik, ps.sector, ps.last_trade_date) == (
        1000001,
        "Technology",
        date(2024, 1, 16),
    )
    assert ps.risk_label == "high"  # +/-5% a day while the lot is open
    # YTD runs 2023-12-29 .. 2024-03-01 (43 sessions). The full sale takes effect at its own
    # entry: the 01-18 open (filed) or the 01-16 close (executed).
    assert _window(session, 2000001, "filed", "ytd").time_invested_pct == pytest.approx(12 / 43)
    assert _window(session, 2000001, "executed", "ytd").time_invested_pct == pytest.approx(11 / 43)


def test_insider_nav_matches_the_stored_windows(session):
    _trading_world(session)
    compute_profile_stats(session, as_of=CC_AS_OF)

    nav = insider_nav(session, 2000001, basis="filed", include_10b5_1=False, as_of=CC_AS_OF)

    assert nav.index[0] == date(2023, 11, 3)  # the buy's filed entry (next session's open)
    ytd = window_stats(nav, CC_AS_OF)[0]
    assert ytd.ret == pytest.approx(_window(session, 2000001, "filed", "ytd").ret)


# ------------------------------------------------------------------------------ funds
FUND_AS_OF = date(2024, 6, 28)


def _fund_prices(session, symbol: str, price: Callable[[date], float]) -> None:
    days = trading_days(date(2023, 9, 1), FUND_AS_OF)
    make_prices(session, symbol, days[0], [price(d) for d in days])


def _fund(session, cik: int, cusip: str, filings: list[tuple[date, datetime]]) -> None:
    make_fund_manager(session, cik=cik, name=f"Fund {cik}", is_tracked=cik != 3000003)
    for n, (period, accepted_at) in enumerate(filings, start=1):
        acc = f"{cik:010d}-24-{n:06d}"
        make_fund_filing(
            session,
            accession_no=acc,
            filer_cik=cik,
            period=period,
            filed_date=accepted_at.date(),
            accepted_at=accepted_at,
        )
        make_fund_position(session, accession_no=acc, filer_cik=cik, period=period, cusip=cusip)


def _fund_world(session) -> None:
    def aaa(d: date) -> float:
        if d < date(2023, 11, 1):
            return 10.0
        return 11.0 if d < date(2024, 2, 1) else 12.1

    _fund_prices(session, "AAA", aaa)
    for symbol, level in (("BBB", 20.0), ("SPY", 100.0), ("QQQ", 100.0)):
        _fund_prices(session, symbol, lambda d, level=level: level)
    make_security(session, cusip="000000AA1", issuer_cik=None, ticker="AAA", name="AAA")
    make_security(session, cusip="000000BB2", issuer_cik=None, ticker="BBB", name="BBB")
    q3, q4, q1 = date(2023, 9, 30), date(2023, 12, 31), date(2024, 3, 31)
    _fund(
        session,
        3000001,
        "000000AA1",
        [
            (q3, datetime(2023, 11, 14, 16, 30, tzinfo=ET)),
            (q4, datetime(2024, 2, 14, 16, 30, tzinfo=ET)),
            (q1, datetime(2024, 5, 15, 16, 30, tzinfo=ET)),
        ],
    )
    _fund(
        session,
        3000002,
        "000000BB2",
        [
            (q4, datetime(2024, 2, 13, 16, 30, tzinfo=ET)),
            (q1, datetime(2024, 5, 14, 16, 30, tzinfo=ET)),
        ],
    )
    _fund(session, 3000003, "000000AA1", [(q1, datetime(2024, 5, 15, 16, 30, tzinfo=ET))])


def test_fund_stats_from_quarterly_excess(session):
    _fund_world(session)

    assert compute_fund_stats(session, as_of=FUND_AS_OF) == 4  # 2 tracked funds x 2 bases

    # executed: AAA +10% over Q3 (09-29 -> 12-29) and Q4 (12-29 -> 03-28); BBB flat over Q4
    a, b = (
        _stats(session, 3000001, "executed", kind="fund"),
        _stats(session, 3000002, "executed", kind="fund"),
    )
    mu = (2 * 0.10 + 1 * 0.0) / 3
    assert (a.n_complete, a.avg_roi_6m, a.hit_rate) == (2, pytest.approx(0.10), 1.0)
    assert a.shrunk_mean == pytest.approx((2 * 0.10 + 4 * mu) / 6)
    assert b.shrunk_mean == pytest.approx(4 * mu / 5)
    assert (a.rating, b.rating, a.confidence, a.risk_label) == (100, 0, "low", "low")
    # filed: entries at the opens after acceptance; AAA's +10% lands in the Q3 holding period
    assert _stats(session, 3000001, kind="fund").avg_roi_6m == pytest.approx(0.05)
    assert session.get(ProfileStats, ("fund", 3000003, "filed", False)) is None  # untracked

    last = session.get(FundNavDaily, (3000001, "executed", FUND_AS_OF))
    assert last is not None and last.nav == pytest.approx(1.21) and last.coverage == 1.0
    ytd = _window(session, 3000001, "executed", "ytd", kind="fund")
    assert ytd.ret == pytest.approx(0.10) and ytd.time_invested_pct == 1.0


def test_fund_stats_scoped_run_replaces_only_that_fund(session):
    _fund_world(session)
    compute_fund_stats(session, as_of=FUND_AS_OF)
    before = session.scalar(select(func.count()).select_from(FundNavDaily))

    assert compute_fund_stats(session, filer_ciks=[3000002], as_of=FUND_AS_OF) == 2

    assert session.scalar(select(func.count()).select_from(FundNavDaily)) == before
    assert _stats(session, 3000001, "executed", kind="fund").rating == 100
    assert _stats(session, 3000002, "executed", kind="fund").rating == 0
