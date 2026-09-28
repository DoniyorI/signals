"""yfinance fallback daily bars: used when there's no Alpaca key or Alpaca lacks a symbol
(spec 7.8). Rate-limited and fragile, so fallback only, and batched to be gentler on it.
"""

import time
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from typing import Any, cast

import pandas as pd
import yfinance

BAR_FIELDS = ("Open", "High", "Low", "Close", "Adj Close", "Volume")


def _yahoo_symbol(symbol: str) -> str:
    """Canonical dot style to Yahoo's dash style (BRK.B -> BRK-B); only at this boundary."""
    return symbol.replace(".", "-")


def _symbol_frame(
    frame: pd.DataFrame, yahoo_symbol: str, *, single_batch: bool
) -> pd.DataFrame | None:
    """This ticker's OHLCV sub-frame from a `group_by="ticker"` download, or None if
    Yahoo returned nothing for it."""
    if isinstance(frame.columns, pd.MultiIndex):
        if yahoo_symbol not in frame.columns.get_level_values(0):
            return None
        return cast(pd.DataFrame, frame[yahoo_symbol])
    # A single-ticker request sometimes comes back with flat (non-MultiIndex) columns.
    return frame if single_batch else None


class YFinanceProvider:
    name = "yfinance"

    def __init__(
        self,
        download: Callable[..., pd.DataFrame] | None = None,
        *,
        batch: int = 50,
        pause_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._download = download or yfinance.download
        self._batch = batch
        self._pause_s = pause_s
        self._sleep = sleep

    def daily_bars(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        """Columns: BAR_COLUMNS without `source`. Rows with no close (Yahoo has nothing
        for that day) are dropped -- a missing bar is simply missing."""
        unique = list(dict.fromkeys(symbols))
        rows: list[dict[str, Any]] = []
        for i in range(0, len(unique), self._batch):
            batch = unique[i : i + self._batch]
            if i > 0:
                self._sleep(self._pause_s)
            yahoo_by_canonical = {s: _yahoo_symbol(s) for s in batch}
            frame = self._download(
                tickers=" ".join(yahoo_by_canonical.values()),
                start=start,
                end=end + timedelta(days=1),
                auto_adjust=False,
                actions=False,
                group_by="ticker",
                threads=False,
                progress=False,
            )
            if frame is None:  # Yahoo returned nothing at all for this batch
                continue
            for canonical, yahoo_symbol in yahoo_by_canonical.items():
                sub = _symbol_frame(frame, yahoo_symbol, single_batch=len(batch) == 1)
                if sub is None:
                    continue
                rows.extend(_rows_for_symbol(canonical, sub))
        columns = ["symbol", "date", "open", "high", "low", "close", "volume", "adj_close"]
        df = pd.DataFrame(rows, columns=columns)
        return df.sort_values(["symbol", "date"]).reset_index(drop=True)


def _rows_for_symbol(symbol: str, sub: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ts, bar in sub.iterrows():
        close = bar.get("Close")
        if pd.isna(close):
            continue
        rows.append(
            {
                "symbol": symbol,
                "date": pd.Timestamp(cast(Any, ts)).date(),
                "open": bar.get("Open"),
                "high": bar.get("High"),
                "low": bar.get("Low"),
                "close": close,
                "volume": bar.get("Volume"),
                "adj_close": bar.get("Adj Close"),
            }
        )
    return rows
