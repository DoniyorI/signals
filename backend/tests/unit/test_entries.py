from datetime import UTC, date, datetime

import pytest

from signals.analytics.entries import Entry, executed_entry, filed_entry
from signals.analytics.series import IssuerSeries
from signals.domain.calendars import ET, trading_days
from tests.analytics_support import empty_series, series_from_bars


@pytest.fixture
def series() -> IssuerSeries:
    """open 10, close 11, factor 1 except 0.5 from 2024-05-28 to 2024-06-07."""
    bars: dict[date, tuple[float, float, float]] = {}
    for start, end, factor in [
        (date(2024, 3, 25), date(2024, 4, 5), 1.0),
        (date(2024, 5, 28), date(2024, 6, 7), 0.5),
        (date(2024, 11, 25), date(2024, 12, 6), 1.0),
    ]:
        for d in trading_days(start, end):
            bars[d] = (10.0, 11.0, factor)
    return series_from_bars(bars)


def _filed(accepted: datetime | None, filed_date: date, s: IssuerSeries) -> Entry:
    e = filed_entry(accepted, filed_date, s)
    assert e is not None
    return e


@pytest.mark.parametrize(
    "accepted,expected",
    [
        (datetime(2024, 3, 28, 8, 15, tzinfo=ET), (date(2024, 3, 28), "open", 10.0)),
        (datetime(2024, 3, 28, 11, 0, tzinfo=ET), (date(2024, 3, 28), "close", 11.0)),
        (datetime(2024, 3, 28, 16, 5, tzinfo=ET), (date(2024, 4, 1), "open", 10.0)),  # Good Friday
        (datetime(2024, 3, 29, 10, 0, tzinfo=ET), (date(2024, 4, 1), "open", 10.0)),  # SEC open
        (datetime(2024, 3, 28, 16, 0, tzinfo=ET), (date(2024, 4, 1), "open", 10.0)),  # at 16:00
        (
            datetime(2024, 11, 29, 13, 30, tzinfo=ET),
            (date(2024, 12, 2), "open", 10.0),
        ),  # early close
        (datetime(2024, 11, 29, 12, 59, tzinfo=ET), (date(2024, 11, 29), "close", 11.0)),
        (datetime(2024, 6, 3, 8, 0, tzinfo=ET), (date(2024, 6, 3), "open", 5.0)),  # adjusted
    ],
)
def test_filed_entry_timing(series, accepted, expected):
    e = _filed(accepted, accepted.date(), series)
    assert (e.date, e.kind, e.price_adj) == expected and e.flags == ()


def test_filed_entry_converts_utc_to_eastern(series):
    e = _filed(datetime(2024, 3, 28, 12, 15, tzinfo=UTC), date(2024, 3, 28), series)  # 08:15 EDT
    assert (e.date, e.kind) == (date(2024, 3, 28), "open")


def test_filed_entry_unknown_acceptance(series):
    e = _filed(None, date(2024, 3, 28), series)
    assert (e.date, e.kind, e.flags) == (date(2024, 4, 1), "open", ("acceptance_unknown",))


def test_filed_entry_steps_over_missing_bar():
    s = series_from_bars({date(2024, 6, 3): (10.0, 11.0, 1.0), date(2024, 6, 5): (12.0, 13.0, 1.0)})
    e = _filed(datetime(2024, 6, 3, 11, 0, tzinfo=ET), date(2024, 6, 3), s)
    assert (e.date, e.kind, e.price_adj) == (date(2024, 6, 3), "close", 11.0)
    gap = _filed(datetime(2024, 6, 3, 17, 0, tzinfo=ET), date(2024, 6, 3), s)  # Jun 4 missing
    assert (gap.date, gap.kind, gap.price_adj, gap.flags) == (
        date(2024, 6, 5),
        "open",
        12.0,
        ("entry_gap",),
    )
    both = _filed(None, date(2024, 6, 3), s)
    assert both.flags == ("acceptance_unknown", "entry_gap")


def test_filed_entry_gives_up_after_five_trading_days(series):
    # Apr 5 after the close: Apr 8 .. Apr 12 have no bars (the series resumes May 28)
    assert filed_entry(datetime(2024, 4, 5, 17, 0, tzinfo=ET), date(2024, 4, 5), series) is None


def test_executed_entry_applies_split_factor(series):
    e = executed_entry(date(2024, 6, 3), 100.0, series)
    assert e is not None and (e.date, e.price_adj, e.kind) == (date(2024, 6, 3), 50.0, "reported")


def test_executed_entry_weekend_trade(series):
    e = executed_entry(date(2024, 6, 1), 100.0, series)
    assert e is not None and (e.date, e.price_adj) == (date(2024, 6, 3), 50.0)


def test_executed_entry_missing_price(series):
    e = executed_entry(date(2024, 6, 3), None, series)
    assert e is not None and (e.price_adj, e.kind) == (5.5, "close_fallback")
    assert e.flags == ("price_missing",)
    zero = executed_entry(date(2024, 6, 3), 0.0, series)
    assert zero is not None and zero.kind == "close_fallback"


def test_executed_entry_uses_session_factor_when_nothing_earlier():
    s = series_from_bars({date(2024, 6, 3): (10.0, 11.0, 0.5)})
    e = executed_entry(date(2024, 6, 1), 20.0, s)  # Saturday before the first bar
    assert e is not None and (e.date, e.price_adj) == (date(2024, 6, 3), 10.0)


def test_executed_entry_none_without_prices(series):
    assert executed_entry(date(2024, 3, 1), 100.0, series) is None  # before any bar
    assert executed_entry(date(2024, 4, 10), None, series) is None  # no bar that day


def test_entry_none_without_prices():
    assert (
        filed_entry(datetime(2024, 3, 28, 8, 0, tzinfo=ET), date(2024, 3, 28), empty_series())
        is None
    )
    assert executed_entry(date(2024, 3, 28), 10.0, empty_series()) is None
