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
