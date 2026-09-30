from datetime import date

import pytest

from signals.analytics.copycat import Lot, SaleEvent, copycat_nav
from signals.analytics.entries import Entry
from signals.analytics.series import BenchPanel, IssuerSeries
from tests.analytics_support import bench_of, series_from_bars, series_on_days

D2, D3, D4, D5, D8 = (date(2024, 1, d) for d in (2, 3, 4, 5, 8))


def _flat(values: list[float]) -> IssuerSeries:
    return series_on_days(D2, values)


# ------------------------------------------------------------------ series fixtures
@pytest.fixture
def stock_10_11_11() -> IssuerSeries:
    return _flat([10.0, 11.0, 11.0])


@pytest.fixture
def stock_open10_close105() -> IssuerSeries:
    return series_from_bars({D2: (10.0, 10.0, 1.0), D3: (10.0, 10.5, 1.0)})


@pytest.fixture
def stock_up_10pct() -> IssuerSeries:
    return _flat([10.0, 11.0])


@pytest.fixture
def stock_flat() -> IssuerSeries:
    return _flat([10.0] * 5)


@pytest.fixture
def stock_flat_then_up10() -> IssuerSeries:
    return _flat([10.0, 10.0, 11.0])


@pytest.fixture
def stock_up_10pct_daily() -> IssuerSeries:
    return _flat([10.0, 11.0, 12.1, 13.31])


@pytest.fixture
def stock_ends_0103() -> IssuerSeries:
    return _flat([10.0, 10.5])


def _bench(spy: list[float], **extra: list[float]) -> BenchPanel:
    return bench_of(SPY=_flat(spy), QQQ=_flat(spy), **{k: _flat(v) for k, v in extra.items()})


@pytest.fixture
def bench_up_1pct() -> BenchPanel:
    return _bench([100.0 * 1.01**i for i in range(5)])


@pytest.fixture
def bench_flat() -> BenchPanel:
    return _bench([100.0] * 5)


@pytest.fixture
def bench_up_2pct_on_day4() -> BenchPanel:
    return _bench([100.0, 100.0, 102.0, 102.0, 102.0])


@pytest.fixture
def bench_xlk_up3_on_0103() -> BenchPanel:
    return _bench([100.0] * 5, XLK=[100.0, 103.0, 103.0, 103.0, 103.0])


def _step(nav, a: date, b: date) -> float:
    return nav.at[b, "nav"] / nav.at[a, "nav"] - 1


# ------------------------------------------------------------------ plan tests
def test_no_lots_tracks_spy(bench_up_1pct):
    nav = copycat_nav([], [], bench_up_1pct, D2, D4)
    assert list(nav["nav"].round(6)) == [1.0, 1.01, 1.0201]
    assert list(nav["spy"].round(6)) == [1.0, 1.01, 1.0201] and (nav["invested"] == 0).all()


def test_single_lot_full_weight(stock_10_11_11, bench_up_1pct):
    lot = Lot(1, 1000001, stock_10_11_11, Entry(D2, 10.0, "close"), None)
    nav = copycat_nav([lot], [], bench_up_1pct, D2, D4)
    assert nav.at[D3, "nav"] == pytest.approx(1.10) and nav.at[D4, "nav"] == pytest.approx(1.10)
    assert list(nav["invested"]) == [0.0, 1.0, 1.0]


def test_open_entry_earns_open_to_close(stock_open10_close105, bench_flat):
    lot = Lot(1, 1000001, stock_open10_close105, Entry(D3, 10.0, "open"), None)
    nav = copycat_nav([lot], [], bench_flat, D2, D3)
    assert nav.at[D3, "nav"] == pytest.approx(1.05)


def test_two_lots_equal_weight(stock_up_10pct, stock_flat, bench_flat):
    lots = [
        Lot(1, 1, stock_up_10pct, Entry(D2, 10.0, "close"), None),
        Lot(2, 2, stock_flat, Entry(D2, 10.0, "close"), None),
    ]
    assert copycat_nav(lots, [], bench_flat, D2, D3).iloc[-1]["nav"] == pytest.approx(1.05)


def test_partial_sale_moves_money_to_spy(stock_flat_then_up10, bench_up_2pct_on_day4):
    lot = Lot(1, 1000001, stock_flat_then_up10, Entry(D2, 10.0, "close"), None)
    sale = SaleEvent(1000001, Entry(D3, 10.0, "close"), 0.5)
    nav = copycat_nav([lot], [sale], bench_up_2pct_on_day4, D2, D4)
    assert _step(nav, D3, D4) == pytest.approx(0.06)
    assert list(nav["invested"]) == [0.0, 1.0, 0.5]


def test_lot_closes_after_hold_days(stock_up_10pct_daily, bench_up_1pct):
    lot = Lot(1, 1, stock_up_10pct_daily, Entry(D2, 10.0, "close"), None)
    nav = copycat_nav([lot], [], bench_up_1pct, D2, D5, hold_days=2)
    assert _step(nav, D4, D5) == pytest.approx(0.01)
    assert _step(nav, D3, D4) == pytest.approx(0.10)


def test_min_weight_closes_lot(stock_flat_then_up10, bench_up_2pct_on_day4):
    lot = Lot(1, 1000001, stock_flat_then_up10, Entry(D2, 10.0, "close"), None)
    sale = SaleEvent(1000001, Entry(D3, 10.0, "close"), 0.96)  # w 1.0 -> 0.04 < 0.05 -> closed
    nav = copycat_nav([lot], [sale], bench_up_2pct_on_day4, D2, D4)
    assert _step(nav, D3, D4) == pytest.approx(0.02)
    assert nav.at[D4, "invested"] == 0


def test_delisted_lot_no_nan(stock_ends_0103, bench_up_1pct):
    lot = Lot(1, 1000001, stock_ends_0103, Entry(D2, 10.0, "close"), None)
    nav = copycat_nav([lot], [], bench_up_1pct, D2, D4)
    assert nav["nav"].notna().all()
    assert _step(nav, D2, D3) == pytest.approx(0.05)
    assert _step(nav, D3, D4) == pytest.approx(0.01)


def test_sector_column_uses_etf(stock_flat, bench_xlk_up3_on_0103):
    lot = Lot(1, 1000001, stock_flat, Entry(D2, 10.0, "close"), "XLK")
    nav = copycat_nav([lot], [], bench_xlk_up3_on_0103, D2, D3)
    assert nav.at[D3, "sector"] == pytest.approx(1.03) and nav.at[D3, "nav"] == pytest.approx(1.0)


# ------------------------------------------------------------------ edge semantics
def test_sector_falls_back_to_spy_without_etf(stock_flat, bench_up_1pct):
    lots = [
        Lot(1, 1, stock_flat, Entry(D2, 10.0, "close"), None),
        Lot(2, 2, stock_flat, Entry(D2, 10.0, "close"), "XLC"),  # no XLC history
    ]
    nav = copycat_nav(lots, [], bench_up_1pct, D2, D3)
    assert nav.at[D3, "sector"] == pytest.approx(1.01)


def test_sale_hits_every_open_lot_of_that_issuer_only(stock_flat_then_up10, bench_flat):
    lots = [
        Lot(1, 1, stock_flat_then_up10, Entry(D2, 10.0, "close"), None),
        Lot(2, 1, stock_flat_then_up10, Entry(D2, 10.0, "close"), None),
        Lot(3, 2, stock_flat_then_up10, Entry(D2, 10.0, "close"), None),
    ]
    nav = copycat_nav(lots, [SaleEvent(1, Entry(D3, 10.0, "close"), 0.5)], bench_flat, D2, D4)
    assert nav.at[D4, "invested"] == pytest.approx(2.0)  # 0.5 + 0.5 + 1.0
    assert _step(nav, D3, D4) == pytest.approx(0.10)


def test_sale_before_the_lot_opens_does_nothing(stock_flat_then_up10, bench_flat):
    lot = Lot(1, 1, stock_flat_then_up10, Entry(D3, 10.0, "close"), None)
    nav = copycat_nav([lot], [SaleEvent(1, Entry(D2, 10.0, "close"), 0.9)], bench_flat, D2, D4)
    assert nav.at[D4, "invested"] == 1.0 and _step(nav, D3, D4) == pytest.approx(0.10)


def test_open_sale_applies_before_that_days_return(stock_flat_then_up10, bench_up_2pct_on_day4):
    lot = Lot(1, 1, stock_flat_then_up10, Entry(D2, 10.0, "close"), None)
    sale = SaleEvent(1, Entry(D4, 10.5, "open"), 0.5)
    nav = copycat_nav([lot], [sale], bench_up_2pct_on_day4, D2, D4)
    assert _step(nav, D3, D4) == pytest.approx(0.5 * 0.10 + 0.5 * 0.02)


def test_interior_price_gap_carries_last_close(bench_flat):
    gappy = series_from_bars({D2: (10.0, 10.0, 1.0), D4: (12.0, 12.0, 1.0), D5: (12.0, 12.0, 1.0)})
    lot = Lot(1, 1, gappy, Entry(D2, 10.0, "close"), None)
    nav = copycat_nav([lot], [], bench_flat, D2, D5)
    assert nav.at[D3, "nav"] == pytest.approx(1.0) and nav.at[D3, "invested"] == 1.0
    assert nav.at[D4, "nav"] == pytest.approx(1.2)


def test_more_than_one_full_position_is_not_leveraged(stock_up_10pct, bench_flat):
    lots = [Lot(i, 1, stock_up_10pct, Entry(D2, 10.0, "close"), None) for i in range(3)]
    nav = copycat_nav(lots, [], bench_flat, D2, D3)
    assert nav.at[D3, "nav"] == pytest.approx(1.10) and nav.at[D3, "invested"] == 3.0


def test_reported_entry_measured_from_insider_price(stock_10_11_11, bench_flat):
    lot = Lot(1, 1, stock_10_11_11, Entry(D2, 10.5, "reported"), None)
    nav = copycat_nav([lot], [], bench_flat, D2, D3)
    assert nav.at[D3, "nav"] == pytest.approx(11.0 / 10.5)


def test_lot_entering_on_first_day_at_open_keeps_that_days_move(stock_open10_close105, bench_flat):
    lot = Lot(1, 1, stock_open10_close105, Entry(D2, 9.0, "open"), None)
    nav = copycat_nav([lot], [], bench_flat, D2, D3)
    assert nav.at[D2, "nav"] == 1.0 and nav.at[D3, "nav"] == pytest.approx(10.5 / 9.0)


def test_empty_range_is_empty(bench_flat):
    nav = copycat_nav([], [], bench_flat, D8, D2)
    assert nav.empty and list(nav.columns) == ["nav", "spy", "qqq", "sector", "invested"]
