from collections.abc import Callable
from datetime import date, datetime

import pytest

from signals.analytics.funds import (
    fund_copycat_nav,
    fund_periods,
    load_fund_inputs,
    load_fund_periods,
)
from signals.analytics.series import load_bench
from signals.domain.calendars import ET, trading_days
from signals.domain.types import Basis
from tests.factories import (
    make_fund_filing,
    make_fund_manager,
    make_fund_position,
    make_issuer,
    make_prices,
    make_security,
)

FUND = 3000001
Q4, Q1 = date(2023, 12, 31), date(2024, 3, 31)
CUSIP_A, CUSIP_B, CUSIP_C, CUSIP_D = "000000AA1", "000000BB2", "000000CC3", "000000DD4"
FIRST, LAST = date(2023, 11, 1), date(2024, 6, 28)


def _prices(
    session, symbol: str, price: Callable[[date], float], start: date = FIRST, end: date = LAST
) -> None:
    days = trading_days(start, end)
    make_prices(session, symbol, days[0], [price(d) for d in days])


def _filing(session, n: int, period: date, accepted_at: datetime) -> str:
    filing = make_fund_filing(
        session,
        accession_no=f"0003000001-24-{n:06d}",
        period=period,
        filed_date=accepted_at.date(),
        accepted_at=accepted_at,
    )
    return filing.accession_no


def _securities(session, *pairs: tuple[str, str]) -> None:
    for cusip, ticker in pairs:
        make_security(session, cusip=cusip, issuer_cik=None, ticker=ticker, name=ticker)


def _world(session, *symbols: str) -> None:
    make_fund_manager(session)
    for symbol in (*symbols, "SPY", "QQQ"):
        _prices(session, symbol, lambda d: 10.0)


def test_unpriced_excluded_coverage(session):
    _world(session, "AAA", "BBB")
    acc = _filing(session, 1, Q1, datetime(2024, 5, 15, 16, 30, tzinfo=ET))
    _securities(session, (CUSIP_A, "AAA"), (CUSIP_B, "BBB"))  # CUSIP_C has no mapping
    for cusip, value in ((CUSIP_A, 40.0), (CUSIP_B, 40.0), (CUSIP_C, 20.0)):
        make_fund_position(session, accession_no=acc, period=Q1, cusip=cusip, value_usd=value)

    periods, panel = load_fund_periods(session, FUND, basis=Basis.EXECUTED)

    assert len(periods) == 1
    p = periods[0]
    # 2024-03-31 is a Sunday and 03-29 Good Friday: the last trading day is 03-28
    assert (p.period, p.start, p.start_kind) == (Q1, date(2024, 3, 28), "close")
    assert p.weights == pytest.approx({"AAA": 0.5, "BBB": 0.5})
    assert p.coverage == pytest.approx(0.8)
    assert set(panel) == {"AAA", "BBB"}


def test_holding_without_prices_in_the_period_is_excluded(session):
    _world(session, "AAA", "BBB")
    _prices(session, "CCC", lambda d: 5.0, end=date(2024, 2, 29))  # stops before the period
    acc = _filing(session, 1, Q1, datetime(2024, 5, 15, 16, 30, tzinfo=ET))
    _securities(session, (CUSIP_A, "AAA"), (CUSIP_B, "BBB"), (CUSIP_C, "CCC"))
    for cusip, value in ((CUSIP_A, 40.0), (CUSIP_B, 40.0), (CUSIP_C, 20.0)):
        make_fund_position(session, accession_no=acc, period=Q1, cusip=cusip, value_usd=value)

    (p,), _ = load_fund_periods(session, FUND, basis=Basis.EXECUTED)

    assert p.weights == pytest.approx({"AAA": 0.5, "BBB": 0.5}) and p.coverage == pytest.approx(0.8)


def test_options_and_superseded_rows_ignored(session):
    _world(session, "AAA", "BBB", "DDD")
    old = _filing(session, 1, Q1, datetime(2024, 5, 15, 16, 30, tzinfo=ET))
    new = _filing(session, 2, Q1, datetime(2024, 5, 20, 16, 30, tzinfo=ET))
    _securities(session, (CUSIP_A, "AAA"), (CUSIP_B, "BBB"), (CUSIP_D, "DDD"))
    make_fund_position(session, accession_no=old, period=Q1, cusip=CUSIP_D, is_effective=False)
    make_fund_position(session, accession_no=new, period=Q1, cusip=CUSIP_A, value_usd=30.0)
    make_fund_position(session, accession_no=new, period=Q1, cusip=CUSIP_B, value_usd=10.0)
    make_fund_position(
        session, accession_no=new, period=Q1, cusip=CUSIP_A, value_usd=500.0, put_call="CALL"
    )

    (p,), _ = load_fund_periods(session, FUND, basis=Basis.EXECUTED)

    assert p.weights == pytest.approx({"AAA": 0.75, "BBB": 0.25}) and p.coverage == 1.0


def test_filed_start_is_the_first_13f_disclosure_of_the_period(session):
    _world(session, "AAA")
    make_fund_filing(
        session,
        accession_no="0003000001-24-000009",
        period=Q1,
        filed_date=date(2024, 5, 10),
        accepted_at=datetime(2024, 5, 10, 16, 30, tzinfo=ET),
        submission_type="13F-NT",  # a notice carries no holdings
    )
    original = _filing(session, 1, Q1, datetime(2024, 5, 15, 16, 30, tzinfo=ET))
    restated = _filing(session, 2, Q1, datetime(2024, 5, 20, 16, 30, tzinfo=ET))
    _securities(session, (CUSIP_A, "AAA"))
    make_fund_position(session, accession_no=original, period=Q1, cusip=CUSIP_A, is_effective=False)
    make_fund_position(session, accession_no=restated, period=Q1, cusip=CUSIP_A)

    (p,), _ = load_fund_periods(session, FUND, basis=Basis.FILED)

    assert (p.start, p.start_kind) == (date(2024, 5, 16), "open")


def test_end_hides_later_filings(session):
    _world(session, "AAA", "BBB")
    q4 = _filing(session, 1, Q4, datetime(2024, 2, 14, 16, 30, tzinfo=ET))
    q1 = _filing(session, 2, Q1, datetime(2024, 5, 15, 16, 30, tzinfo=ET))
    _securities(session, (CUSIP_A, "AAA"), (CUSIP_B, "BBB"))
    make_fund_position(session, accession_no=q4, period=Q4, cusip=CUSIP_A)
    make_fund_position(session, accession_no=q1, period=Q1, cusip=CUSIP_B)

    inputs = load_fund_inputs(session, FUND, end=date(2024, 5, 14))

    assert [b.period for b in inputs.books] == [Q4]
    assert inputs.panel["AAA"].last_date() == date(2024, 5, 14)


def test_tickers_are_canonical_and_mapped_to_sector_etfs(session):
    make_issuer(session, cik=1000009, name="Berkshire", sector="Financials", ticker=None)
    _world(session, "BRK.B")
    acc = _filing(session, 1, Q1, datetime(2024, 5, 15, 16, 30, tzinfo=ET))
    make_security(session, cusip=CUSIP_A, issuer_cik=1000009, ticker="BRK-B", name="BRK")
    make_fund_position(session, accession_no=acc, period=Q1, cusip=CUSIP_A)

    inputs = load_fund_inputs(session, FUND)

    assert fund_periods(inputs, Basis.EXECUTED)[0].weights == {"BRK.B": 1.0}
    assert inputs.sector_etfs == {"BRK.B": "XLF"}


def test_filed_basis_holds_previous_until_filing(session):
    make_fund_manager(session)
    first = _filing(session, 1, Q4, datetime(2024, 2, 14, 16, 30, tzinfo=ET))  # after the close
    second = _filing(session, 2, Q1, datetime(2024, 5, 15, 10, 0, tzinfo=ET))  # in the session
    _securities(session, (CUSIP_A, "AAA"), (CUSIP_B, "BBB"))
    make_fund_position(session, accession_no=first, period=Q4, cusip=CUSIP_A, value_usd=100.0)
    make_fund_position(session, accession_no=second, period=Q1, cusip=CUSIP_B, value_usd=100.0)
    _prices(session, "AAA", lambda d: 11.0 if d >= date(2024, 5, 14) else 10.0)
    _prices(session, "BBB", lambda d: 22.0 if d >= date(2024, 5, 16) else 20.0)
    for symbol in ("SPY", "QQQ"):
        _prices(session, symbol, lambda d: 100.0)

    periods, panel = load_fund_periods(session, FUND, basis=Basis.FILED)
    assert [(p.period, p.start, p.start_kind) for p in periods] == [
        (Q4, date(2024, 2, 15), "open"),
        (Q1, date(2024, 5, 15), "close"),
    ]
    nav = fund_copycat_nav(periods, panel, load_bench(session, FIRST, LAST), end=LAST)["nav"]

    # the day before period 2's entry the fund still holds period 1's AAA (+10% that day)
    assert nav[date(2024, 5, 14)] / nav[date(2024, 5, 13)] - 1 == pytest.approx(0.10)
    assert nav[date(2024, 5, 15)] == pytest.approx(nav[date(2024, 5, 14)])
    # from the entry (05-15 close) it holds BBB (+10% on 05-16)
    assert nav[date(2024, 5, 16)] / nav[date(2024, 5, 15)] - 1 == pytest.approx(0.10)


def test_same_day_filings_keep_only_the_latest_period(session):
    _world(session, "AAA", "BBB")
    at = datetime(2024, 5, 15, 10, 0, tzinfo=ET)  # a late Q4 report filed with the Q1 one
    q4, q1 = _filing(session, 1, Q4, at), _filing(session, 2, Q1, at)
    _securities(session, (CUSIP_A, "AAA"), (CUSIP_B, "BBB"))
    make_fund_position(session, accession_no=q4, period=Q4, cusip=CUSIP_A)
    make_fund_position(session, accession_no=q1, period=Q1, cusip=CUSIP_B)

    filed, _ = load_fund_periods(session, FUND, basis=Basis.FILED)
    executed, _ = load_fund_periods(session, FUND, basis=Basis.EXECUTED)

    assert [p.period for p in filed] == [Q1]
    assert [(p.period, p.start) for p in executed] == [
        (Q4, date(2023, 12, 29)),
        (Q1, date(2024, 3, 28)),
    ]


def test_period_without_priced_holdings_is_dropped(session):
    _world(session, "BBB")
    q4 = _filing(session, 1, Q4, datetime(2024, 2, 14, 16, 30, tzinfo=ET))
    q1 = _filing(session, 2, Q1, datetime(2024, 5, 15, 16, 30, tzinfo=ET))
    _securities(session, (CUSIP_B, "BBB"))
    make_fund_position(session, accession_no=q4, period=Q4, cusip=CUSIP_C)  # unmapped only
    make_fund_position(session, accession_no=q1, period=Q1, cusip=CUSIP_B)

    periods, _ = load_fund_periods(session, FUND, basis=Basis.EXECUTED)

    assert [(p.period, p.weights) for p in periods] == [(Q1, {"BBB": 1.0})]
