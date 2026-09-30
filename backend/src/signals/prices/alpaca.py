"""Alpaca daily bars: raw and split/dividend-adjusted, two requests per batch (spec 7.8).

`adjustment=raw` supplies OHLCV; `adjustment=all` supplies `adj_close` (so
`adj_factor = adj_close / close` for any date). Bars are matched between the two passes
by their `t` timestamp, which is identical across both. Each bar's `t` (UTC) is converted
to its US/Eastern calendar date -- Alpaca's daily bars are timestamped at the session's
open, so this is always the trading day the bar covers.
"""

import time
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

import httpx
import pandas as pd

from signals.domain.calendars import ET

BARS_PATH = "/v2/stocks/bars"
MAX_429_RETRIES = 5
RETRY_SLEEP_S = 60.0


class FeedNotPermitted(Exception):
    """The Alpaca key's plan does not permit the requested feed (for example free-tier SIP)."""


class _BadRequest(Exception):
    """400/422 for a batch of symbols; the caller isolates the bad one(s) by splitting."""


def _bar_date(raw_t: str) -> date:
    return datetime.fromisoformat(raw_t.replace("Z", "+00:00")).astimezone(ET).date()


class AlpacaProvider:
    name = "alpaca"

    def __init__(
        self,
        http: httpx.Client,
        key_id: str,
        secret: str,
        *,
        feed: str = "sip",
        base_url: str = "https://data.alpaca.markets",
        symbols_per_request: int = 100,
        min_interval_s: float = 0.31,
        sleep=time.sleep,
        clock=time.monotonic,
    ) -> None:
        self._http = http
        self._key_id = key_id
        self._secret = secret
        self._feed = feed
        self._base_url = base_url.rstrip("/")
        self._symbols_per_request = symbols_per_request
        self._min_interval_s = min_interval_s
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    @property
    def _headers(self) -> dict[str, str]:
        return {"APCA-API-KEY-ID": self._key_id, "APCA-API-SECRET-KEY": self._secret}

    def _throttle(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            wait = self._min_interval_s - (now - self._last_request)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_request = now

    def _send(self, params: dict[str, Any]) -> dict[str, Any]:
        attempt = 0
        while True:
            self._throttle()
            resp = self._http.get(
                f"{self._base_url}{BARS_PATH}", params=params, headers=self._headers
            )
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 403:
                if "subscription" in resp.text.lower():
                    raise FeedNotPermitted(resp.text)
                resp.raise_for_status()
            if resp.status_code in (400, 422):
                raise _BadRequest(resp.text)
            if resp.status_code == 429 and attempt < MAX_429_RETRIES:
                self._sleep(RETRY_SLEEP_S)
                attempt += 1
                continue
            resp.raise_for_status()
            raise httpx.HTTPStatusError(
                f"unexpected Alpaca status {resp.status_code}", request=resp.request, response=resp
            )

    def _fetch_batch(
        self, symbols: Sequence[str], start: date, end: date, adjustment: str
    ) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
        """(bars per symbol, skipped symbols) for one batch, splitting the batch in half
        on a 400/422 to isolate the bad symbol(s); a lone bad symbol is skipped."""
        try:
            bars: dict[str, list[dict[str, Any]]] = {}
            page_token: str | None = None
            while True:
                params: dict[str, Any] = {
                    "symbols": ",".join(symbols),
                    "timeframe": "1Day",
                    "start": f"{start.isoformat()}T00:00:00Z",
                    "end": f"{end.isoformat()}T23:59:59Z",
                    "limit": 10000,
                    "adjustment": adjustment,
                    "feed": self._feed,
                    "sort": "asc",
                }
                if page_token is not None:
                    params["page_token"] = page_token
                doc = self._send(params)
                for symbol, rows in (doc.get("bars") or {}).items():
                    bars.setdefault(symbol, []).extend(rows)
                page_token = doc.get("next_page_token")
                if not page_token:
                    return bars, []
        except _BadRequest:
            if len(symbols) == 1:
                return {}, [symbols[0]]
            mid = len(symbols) // 2
            left_bars, left_skipped = self._fetch_batch(symbols[:mid], start, end, adjustment)
            right_bars, right_skipped = self._fetch_batch(symbols[mid:], start, end, adjustment)
            return {**left_bars, **right_bars}, [*left_skipped, *right_skipped]

    def daily_bars(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        """Columns: BAR_COLUMNS without `source`. Nothing is invented: a symbol Alpaca has
        no data for is simply absent, and its name is listed in `df.attrs["skipped"]`."""
        unique = list(dict.fromkeys(symbols))
        raw_by_symbol: dict[str, list[dict[str, Any]]] = {}
        adj_by_symbol: dict[str, list[dict[str, Any]]] = {}
        skipped: set[str] = set()
        for i in range(0, len(unique), self._symbols_per_request):
            batch = unique[i : i + self._symbols_per_request]
            raw, skipped_raw = self._fetch_batch(batch, start, end, "raw")
            adjusted, skipped_adj = self._fetch_batch(batch, start, end, "all")
            raw_by_symbol.update(raw)
            adj_by_symbol.update(adjusted)
            skipped.update(skipped_raw)
            skipped.update(skipped_adj)

        rows: list[dict[str, Any]] = []
        for symbol, bars in raw_by_symbol.items():
            adj_close_by_t = {b["t"]: b["c"] for b in adj_by_symbol.get(symbol, [])}
            for bar in bars:
                rows.append(
                    {
                        "symbol": symbol,
                        "date": _bar_date(bar["t"]),
                        "open": bar.get("o"),
                        "high": bar.get("h"),
                        "low": bar.get("l"),
                        "close": bar.get("c"),
                        "volume": bar.get("v"),
                        "adj_close": adj_close_by_t.get(bar["t"], bar.get("c")),
                    }
                )
        columns = ["symbol", "date", "open", "high", "low", "close", "volume", "adj_close"]
        df = pd.DataFrame(rows, columns=columns)
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        df.attrs["skipped"] = sorted(skipped)
        return df
