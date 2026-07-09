"""Orchestrate fetch -> normalize -> upsert for MLB games."""
from __future__ import annotations

from typing import Callable

from bblmlp.ingest.mlb.schedule import normalize_schedule
from bblmlp.storage import upsert_games

FetchFn = Callable[[str, str], list[dict]]


def ingest_range(
    con, fetch: FetchFn, start_date: str, end_date: str, season: int
) -> int:
    raw = fetch(start_date, end_date)
    rows = normalize_schedule(raw, season=season)
    return upsert_games(con, rows)


def season_date_range(season: int) -> tuple[str, str]:
    return (f"{season}-03-01", f"{season}-11-30")


def ingest_seasons(con, fetch: FetchFn, seasons: list[int]) -> int:
    total = 0
    for season in seasons:
        start, end = season_date_range(season)
        total += ingest_range(con, fetch, start, end, season)
    return total
