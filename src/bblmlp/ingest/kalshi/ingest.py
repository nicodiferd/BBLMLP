"""Kalshi snapshot orchestrator: pull open markets -> normalize/match -> persist.

Every call is one timestamped pull. Unlike the MLB ingest orchestrator, there's no
--date/--backfill mode -- Kalshi has no historical replay endpoint, only "what's open
right now" (see design doc #5).
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import duckdb

from bblmlp.ingest.kalshi.client import fetch_open_markets, fetch_orderbook
from bblmlp.ingest.kalshi.snapshot import normalize_snapshot
from bblmlp.storage import append_rows


def pull_and_snapshot(
    con: duckdb.DuckDBPyConnection,
    snapshot_dir: str | Path,
    *,
    fetch_markets=fetch_open_markets,
    fetch_book=fetch_orderbook,
    pulled_at: _dt.datetime | None = None,
) -> int:
    pulled_at = pulled_at or _dt.datetime.now(_dt.timezone.utc)

    markets = fetch_markets()
    orderbooks = {m["ticker"]: fetch_book(m["ticker"]) for m in markets}
    games_df = con.execute(
        "SELECT game_pk, game_date, game_datetime, home_team_id, away_team_id FROM games"
    ).df()

    df = normalize_snapshot(markets, orderbooks, games_df, pulled_at.isoformat())
    if len(df) == 0:
        return 0

    n = append_rows(con, "kalshi_quotes", df)

    snap_dir = Path(snapshot_dir)
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_path = snap_dir / f"{pulled_at.strftime('%Y%m%dT%H%M%SZ')}.parquet"
    con.register("_kalshi_snap_df", df)
    try:
        con.execute(f"COPY (SELECT * FROM _kalshi_snap_df) TO '{snap_path}' (FORMAT PARQUET)")
    finally:
        con.unregister("_kalshi_snap_df")

    return n
