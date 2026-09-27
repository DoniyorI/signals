"""Check whether the configured Alpaca key can read historical SIP daily bars.

Run from backend/: uv run python ../scripts/probe_alpaca.py
Prints "sip ok: <n> bars" or "sip denied: <status> <body>". Never prints the key.
"""

import httpx

from signals.config import get_settings


def main() -> None:
    s = get_settings()
    if not s.alpaca_api_key or s.alpaca_secret_key is None:
        print("sip denied: no Alpaca key configured")
        return
    resp = httpx.get(
        f"{s.alpaca_data_url}/v2/stocks/bars",
        params={
            "symbols": "SPY",
            "timeframe": "1Day",
            "start": "2016-01-04T00:00:00Z",
            "end": "2016-01-09T00:00:00Z",
            "adjustment": "raw",
            "feed": "sip",
        },
        headers={
            "APCA-API-KEY-ID": s.alpaca_api_key,
            "APCA-API-SECRET-KEY": s.alpaca_secret_key.get_secret_value(),
        },
        timeout=30,
    )
    if resp.status_code == 200:
        bars = resp.json().get("bars", {}).get("SPY", [])
        print(f"sip ok: {len(bars)} bars")
    else:
        print(f"sip denied: {resp.status_code} {resp.text[:200]}")


if __name__ == "__main__":
    main()
