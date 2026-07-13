"""Kalshi trade API client: network calls only. Phase 1 reads are public, no auth
(the RSA-PSS signer for live trading is out of scope for this ingest-only work).
"""
from __future__ import annotations

import httpx

_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


def fetch_open_markets(series: str = "KXMLBGAME") -> list[dict]:
    """Fetch every currently-open market for a series, following pagination."""
    markets: list[dict] = []
    cursor: str | None = None
    with httpx.Client(base_url=_BASE_URL, timeout=30.0) as client:
        while True:
            params = {"series_ticker": series, "status": "open", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            resp = client.get("/markets", params=params)
            resp.raise_for_status()
            data = resp.json()
            markets.extend(data.get("markets", []))
            cursor = data.get("cursor") or None
            if not cursor:
                break
    return markets


def fetch_orderbook(market_ticker: str, depth: int = 10) -> dict:
    """Fetch the order book for a single market."""
    with httpx.Client(base_url=_BASE_URL, timeout=30.0) as client:
        resp = client.get(f"/markets/{market_ticker}/orderbook", params={"depth": depth})
        resp.raise_for_status()
        return resp.json()
