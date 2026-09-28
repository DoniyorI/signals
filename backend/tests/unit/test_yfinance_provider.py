"""yfinance fallback provider: canonical<->Yahoo symbol mapping, NaN drops, batching."""

from datetime import date, timedelta

import pandas as pd

from signals.prices.yfinance_provider import YFinanceProvider


def _fake_frame() -> pd.DataFrame:
    """A MultiIndex frame shaped like `yfinance.download(group_by="ticker")` for two
    tickers: BRK-B's last row has no close (a day it didn't trade / data gap)."""
    dates = pd.date_range("2016-01-04", periods=3, freq="D")
    aapl = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Adj Close": [100.5, 101.5, 102.5],
            "Volume": [1000.0, 1100.0, 1200.0],
        },
        index=dates,
    )
    brkb = pd.DataFrame(
        {
            "Open": [140.0, 141.0, float("nan")],
            "High": [141.0, 142.0, float("nan")],
            "Low": [139.0, 140.0, float("nan")],
            "Close": [140.5, 141.5, float("nan")],
            "Adj Close": [140.5, 141.5, float("nan")],
            "Volume": [500.0, 550.0, float("nan")],
        },
        index=dates,
    )
    return pd.concat({"AAPL": aapl, "BRK-B": brkb}, axis=1)


def test_maps_symbols_drops_nan_and_uses_adj_close():
    captured: dict = {}

    def fake_download(**kwargs):
        captured.update(kwargs)
        return _fake_frame()

    provider = YFinanceProvider(download=fake_download, sleep=lambda s: None)
    start, end = date(2016, 1, 4), date(2016, 1, 6)
    df = provider.daily_bars(["AAPL", "BRK.B"], start, end)

    assert set(df["symbol"]) == {"AAPL", "BRK.B"}
    assert len(df[df["symbol"] == "BRK.B"]) == 2  # the NaN-close row is dropped
    assert len(df[df["symbol"] == "AAPL"]) == 3

    brkb_row = df[df["symbol"] == "BRK.B"].iloc[0]
    assert brkb_row["adj_close"] == 140.5
    assert brkb_row["date"] == date(2016, 1, 4)

    assert captured["tickers"] == "AAPL BRK-B"  # canonical dot -> Yahoo dash
    assert captured["start"] == start
    assert captured["end"] == end + timedelta(days=1)
    assert captured["auto_adjust"] is False
    assert captured["actions"] is False
    assert captured["group_by"] == "ticker"
    assert captured["threads"] is False
    assert captured["progress"] is False


def test_sleeps_between_batches():
    calls = []

    def fake_download(**kwargs):
        return pd.concat({t: _fake_frame()["AAPL"] for t in kwargs["tickers"].split()}, axis=1)

    provider = YFinanceProvider(
        download=fake_download, batch=1, sleep=lambda s: calls.append(s), pause_s=2.5
    )
    provider.daily_bars(["AAPL", "MSFT"], date(2016, 1, 4), date(2016, 1, 6))
    assert calls == [2.5]  # one pause between the two single-symbol batches, none after
