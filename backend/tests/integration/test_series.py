from datetime import date

import pytest
from sqlalchemy.orm import Session

from signals.analytics.series import (
    IssuerSeries,
    load_bench,
    load_issuer_series,
    load_symbol_series,
)
from signals.domain.tickers import rebuild_tickers, record_ticker_evidence
from tests.factories import make_issuer, make_prices


def _globex(session: Session) -> None:
    make_issuer(session, cik=1000002, name="Globex Inc", ticker="GBX", ticker_from=date(2016, 1, 4))
    record_ticker_evidence(session, 1000002, "GBX", date(2016, 1, 4), "t")
    record_ticker_evidence(session, 1000002, "GLBX", date(2022, 6, 10), "t")
    rebuild_tickers(session, [1000002])


def _ret(s: IssuerSeries, a: date, b: date) -> float:
    start, end = s.close_adj(a), s.close_adj(b)
    assert start is not None and end is not None
    return end / start - 1


def test_series_stitches_ticker_change(session):
    _globex(session)
    make_prices(session, "GBX", date(2022, 6, 6), [10.0] * 4, adj_factors=[0.5] * 4)  # Jun 6-9
    make_prices(session, "GLBX", date(2022, 6, 10), [10.1, 10.2], adj_factors=[1.0, 1.0])
    s = load_issuer_series(session, 1000002, date(2022, 6, 1), date(2022, 6, 30))
    assert list(s.frame["symbol"]) == ["GBX"] * 4 + ["GLBX"] * 2
    assert s.close_adj(date(2022, 6, 9)) == pytest.approx(10.0)
    assert _ret(s, date(2022, 6, 9), date(2022, 6, 10)) == pytest.approx(0.01)


def test_series_prefers_current_symbol_history(session):
    _globex(session)
    make_prices(session, "GLBX", date(2022, 6, 6), [10.0, 10.0, 10.0, 10.0, 10.1, 10.2])
    s = load_issuer_series(session, 1000002, date(2022, 6, 1), date(2022, 6, 30))
    assert set(s.frame["symbol"]) == {"GLBX"} and len(s.frame) == 6


def test_factor_on_or_before_weekend(session):
    make_issuer(session)
    make_prices(session, "ACME", date(2024, 5, 31), [100.0], adj_factors=[0.5])
    s = load_issuer_series(session, 1000001, date(2024, 5, 1), date(2024, 6, 30))
    assert s.factor_on_or_before(date(2024, 6, 1)) == 0.5 and s.has(date(2024, 6, 1)) is False
    assert s.factor_on_or_before(date(2024, 5, 30)) is None


def test_series_calibrates_to_new_symbol_history_across_reverse_split(session):
    # GBX traded at 1.00 until the change; the provider's GLBX history shows the same day
    # (raw 1.00) adjusted for a 1:10 reverse split that took effect with the new symbol.
    _globex(session)
    make_prices(session, "GBX", date(2022, 6, 6), [1.0] * 4)  # Jun 6-9, factor 1
    make_prices(session, "GLBX", date(2022, 6, 9), [1.0, 10.1], adj_factors=[10.0, 1.0])
    s = load_issuer_series(session, 1000002, date(2022, 6, 1), date(2022, 6, 30))
    assert list(s.frame["symbol"]) == ["GBX"] * 4 + ["GLBX"]
    assert _ret(s, date(2022, 6, 9), date(2022, 6, 10)) == pytest.approx(0.01)
    assert _ret(s, date(2022, 6, 6), date(2022, 6, 9)) == pytest.approx(0.0)


def test_series_excludes_reused_ticker_bars_of_other_issuer(session):
    make_issuer(session, cik=1000003, name="Old Co", ticker=None)
    make_issuer(session, cik=1000004, name="New Co", ticker=None)
    record_ticker_evidence(session, 1000003, "XYZ", date(2016, 2, 1), "t")
    record_ticker_evidence(session, 1000003, "XYZA", date(2019, 1, 2), "t")
    record_ticker_evidence(session, 1000004, "XYZ", date(2020, 5, 1), "t")
    rebuild_tickers(session, [1000003, 1000004])
    make_prices(session, "XYZ", date(2018, 12, 24), [5.0] * 5)  # Old Co: Dec 24 .. Dec 31
    make_prices(session, "XYZA", date(2019, 1, 2), [5.1, 5.2])
    make_prices(session, "XYZ", date(2020, 5, 1), [20.0, 21.0])  # New Co
    new = load_issuer_series(session, 1000004, date(2018, 1, 1), date(2020, 12, 31))
    assert new.first_date() == date(2020, 5, 1) and len(new.frame) == 2
    old = load_issuer_series(session, 1000003, date(2018, 12, 1), date(2020, 12, 31))
    assert list(old.frame["symbol"]) == ["XYZ"] * 5 + ["XYZA"] * 2
    assert old.last_date() == date(2019, 1, 3)


def test_open_and_close_adjusted(session):
    make_issuer(session)
    make_prices(
        session, "ACME", date(2024, 6, 3), [11.0, 12.0], opens=[10.0, 11.0], adj_factors=[0.5, 1.0]
    )
    s = load_issuer_series(session, 1000001, date(2024, 6, 1), date(2024, 6, 30))
    assert (s.open_adj(date(2024, 6, 3)), s.close_adj(date(2024, 6, 3))) == (5.0, 5.5)
    assert s.close_adj(date(2024, 6, 5)) is None
    assert (s.first_date(), s.last_date()) == (date(2024, 6, 3), date(2024, 6, 4))


def test_issuer_without_tickers_is_empty(session):
    make_issuer(session, ticker=None)
    s = load_issuer_series(session, 1000001, date(2024, 1, 1), date(2024, 12, 31))
    assert s.frame.empty and s.first_date() is None and s.last_date() is None
    assert s.close_adj(date(2024, 6, 3)) is None and s.factor_on_or_before(date(2024, 6, 3)) is None


def test_symbol_series_and_bench(session):
    make_prices(session, "SPY", date(2024, 6, 3), [400.0, 404.0])
    make_prices(session, "XLK", date(2024, 6, 3), [200.0, 202.0])
    spy = load_symbol_series(session, "SPY", date(2024, 6, 1), date(2024, 6, 30))
    assert spy.issuer_cik is None and spy.close_adj(date(2024, 6, 4)) == 404.0
    bench = load_bench(session, date(2024, 6, 1), date(2024, 6, 30))
    assert set(bench.series) == {"SPY", "XLK"}
    xlk = bench.get("XLK")
    assert xlk is not None and xlk.close_adj(date(2024, 6, 3)) == 200.0
    assert bench.get("XLC") is None and bench.get(None) is None
