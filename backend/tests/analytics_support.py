"""Synthetic price series for analytics tests (workstream D). Pure helpers, no database."""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta

import pandas as pd

from signals.analytics.series import BenchPanel, IssuerSeries
from signals.domain.calendars import trading_days


def series_from_bars(
    bars: Mapping[date, tuple[float, float, float]],
    *,
    symbol: str = "TEST",
    issuer_cik: int | None = None,
) -> IssuerSeries:
    """bars: date -> (open, close, adj_factor)."""
    dates = sorted(bars)
    opens = [float(bars[d][0]) for d in dates]
    closes = [float(bars[d][1]) for d in dates]
    factors = [float(bars[d][2]) for d in dates]
    frame = pd.DataFrame(
        {
            "symbol": [symbol] * len(dates),
            "open": opens,
            "close": closes,
            "adj_factor": factors,
            "open_adj": [o * f for o, f in zip(opens, factors, strict=True)],
            "close_adj": [c * f for c, f in zip(closes, factors, strict=True)],
        },
        index=pd.Index(dates, dtype=object, name="date"),
    )
    return IssuerSeries(issuer_cik, frame)


def series_on_days(
    start: date,
    closes: Sequence[float],
    *,
    opens: Sequence[float] | None = None,
    factors: Sequence[float] | None = None,
    symbol: str = "TEST",
    issuer_cik: int | None = None,
) -> IssuerSeries:
    """One bar per NYSE trading day from `start` (like tests.factories.make_prices)."""
    days = trading_days(start, start + timedelta(days=len(closes) * 2 + 10))[: len(closes)]
    return series_from_bars(
        {
            d: (
                opens[i] if opens is not None else closes[i],
                closes[i],
                factors[i] if factors is not None else 1.0,
            )
            for i, d in enumerate(days)
        },
        symbol=symbol,
        issuer_cik=issuer_cik,
    )


def empty_series() -> IssuerSeries:
    return series_from_bars({})


def bench_of(**series: IssuerSeries) -> BenchPanel:
    return BenchPanel(dict(series))
