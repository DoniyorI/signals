from datetime import date, datetime

import pytest
from sqlalchemy import select, update

from signals.analytics.returns import compute_decision_returns
from signals.db.models import Decision, DecisionReturn
from signals.domain.calendars import ET, add_trading_days
from tests.factories import make_decision, make_issuer, make_prices

AS_OF = date(2025, 6, 30)


def _seed_prices(session) -> None:
    closes = [10.0 * 1.001**i for i in range(300)]  # +0.1% a day from 2024-01-02
    make_prices(session, "ACME", date(2024, 1, 2), closes)
    for symbol in ("SPY", "QQQ", "XLK"):
        make_prices(session, symbol, date(2024, 1, 2), [100.0] * 300)


def _rows(session, decision_id: int) -> dict[tuple[str, str], DecisionReturn]:
    rows = session.scalars(select(DecisionReturn).where(DecisionReturn.decision_id == decision_id))
    return {(r.basis, r.horizon): r for r in rows}


def test_compute_decision_returns_rows(session):
    make_issuer(session)
    _seed_prices(session)
    d = make_decision(
        session,
        first_trade_date=date(2024, 1, 12),  # index 8
        vwap=10.0,
        accepted_at=datetime(2024, 1, 16, 16, 30, tzinfo=ET),  # after the close
    )
    assert compute_decision_returns(session, as_of=AS_OF) == 8
    rows = _rows(session, d.id)
    assert len(rows) == 8 and all(r.is_complete for r in rows.values())

    ex = rows[("executed", "1m")]
    assert (ex.entry_date, ex.entry_price_adj, ex.entry_kind) == (
        date(2024, 1, 12),
        10.0,
        "reported",
    )
    assert ex.exit_date == add_trading_days(date(2024, 1, 12), 21)
    assert ex.raw_return == pytest.approx(1.001**29 / 1.0 - 1)
    assert ex.excess_spy == pytest.approx(ex.raw_return) and ex.excess_sector == pytest.approx(
        ex.raw_return
    )

    fi = rows[("filed", "12m")]
    assert (fi.entry_date, fi.entry_kind) == (date(2024, 1, 17), "open")  # index 10
    assert fi.entry_price_adj == pytest.approx(10.0 * 1.001**10)
    assert fi.raw_return == pytest.approx(1.001**252 - 1) and fi.exit_reason == "horizon"

    session.refresh(d)
    assert d.lag_cost == pytest.approx(1.001**10 - 1)


def test_decision_without_prices_gets_no_rows(session):
    make_issuer(session)
    d = make_decision(session)
    assert compute_decision_returns(session, as_of=AS_OF) == 0
    session.refresh(d)
    assert _rows(session, d.id) == {} and d.lag_cost is None


def test_recompute_replaces_only_given_decisions(session):
    make_issuer(session)
    _seed_prices(session)
    d1 = make_decision(session, first_trade_date=date(2024, 1, 12))
    d2 = make_decision(session, first_trade_date=date(2024, 2, 12), owner_ciks=(2000002,))
    assert compute_decision_returns(session, as_of=AS_OF) == 16
    before = {k: r.raw_return for k, r in _rows(session, d2.id).items()}
    session.execute(
        update(DecisionReturn).where(DecisionReturn.decision_id == d1.id).values(raw_return=99.0)
    )
    assert compute_decision_returns(session, decision_ids=[d1.id], as_of=AS_OF) == 8
    session.expire_all()
    assert all(r.raw_return != 99.0 for r in _rows(session, d1.id).values())
    assert {k: r.raw_return for k, r in _rows(session, d2.id).items()} == before
    assert session.get(Decision, d2.id) is not None
