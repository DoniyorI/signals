"""Alpaca daily bars provider: pagination, raw+adjusted merge, and error handling."""

import json
from datetime import date, datetime

import httpx
import pytest

from signals.domain.calendars import ET
from signals.prices.alpaca import AlpacaProvider, FeedNotPermitted
from tests.support import MockRouter

BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"


def _recorded_route(fixture_bytes):
    """Picks the recorded fixture page from the request's `adjustment` and `page_token`."""

    def handle(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        adjustment = params.get("adjustment")
        page = "p2" if "page_token" in params else "p1"
        return httpx.Response(200, content=fixture_bytes(f"alpaca_{adjustment}_{page}"))

    return handle


def _provider(router: MockRouter, **kwargs) -> AlpacaProvider:
    return AlpacaProvider(router.client, "KEY123", "SECRET456", sleep=lambda s: None, **kwargs)


def test_paginates_and_merges(fixture_bytes, manifest):
    router = MockRouter({BARS_URL: _recorded_route(fixture_bytes)})
    provider = _provider(router)
    df = provider.daily_bars(["AAPL", "SPY"], date(2016, 1, 4), date(2016, 2, 29))

    n_total = manifest["alpaca_raw_p1"]["expect"]["n_bars_total"]
    assert df.groupby("symbol").size().to_dict() == n_total
    assert df["date"].min() == date(2016, 1, 4)

    all_first = json.loads(fixture_bytes("alpaca_all_p1"))["bars"]["AAPL"][0]
    expected_date = (
        datetime.fromisoformat(all_first["t"].replace("Z", "+00:00")).astimezone(ET).date()
    )
    row = df[(df["symbol"] == "AAPL") & (df["date"] == expected_date)].iloc[0]
    assert row["adj_close"] == all_first["c"]


def test_headers_and_params(fixture_bytes):
    router = MockRouter({BARS_URL: _recorded_route(fixture_bytes)})
    provider = _provider(router)
    provider.daily_bars(["AAPL", "SPY"], date(2016, 1, 4), date(2016, 2, 29))

    first = router.requests[0]
    assert first.headers["APCA-API-KEY-ID"] == "KEY123"
    assert first.headers["APCA-API-SECRET-KEY"] == "SECRET456"
    assert first.url.params["feed"] == "sip"
    assert first.url.params["timeframe"] == "1Day"


def test_feed_not_permitted():
    body = b'{"message":"subscription does not permit querying recent SIP data"}'
    router = MockRouter({BARS_URL: (403, body)})
    provider = _provider(router)
    with pytest.raises(FeedNotPermitted):
        provider.daily_bars(["AAPL"], date(2016, 1, 4), date(2016, 2, 29))


def test_bad_symbol_isolated():
    def handle(request: httpx.Request) -> httpx.Response:
        symbols = request.url.params["symbols"].split(",")
        if "BAD" in symbols:
            return httpx.Response(422, json={"message": "invalid symbol(s): BAD"})
        bars = {
            s: [{"t": "2016-01-04T05:00:00Z", "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 100}]
            for s in symbols
        }
        return httpx.Response(200, json={"bars": bars, "next_page_token": None})

    router = MockRouter({BARS_URL: handle})
    provider = _provider(router)
    df = provider.daily_bars(["GOOD", "BAD"], date(2016, 1, 4), date(2016, 1, 4))
    assert set(df["symbol"]) == {"GOOD"}
    assert df.attrs["skipped"] == ["BAD"]
