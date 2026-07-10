"""Orchestrate fetch -> normalize -> upsert for MLB games."""
from __future__ import annotations

from typing import Callable

import pandas as pd

from bblmlp.ingest.mlb.schedule import normalize_schedule
from bblmlp.storage import replace_all, replace_partition, upsert_games

FetchFn = Callable[[str, str], list[dict]]


def ingest_range(
    con, fetch: FetchFn, start_date: str, end_date: str, season: int,
    players: pd.DataFrame | None = None,
) -> int:
    raw = fetch(start_date, end_date)
    rows = normalize_schedule(raw, season=season, players=players)
    return upsert_games(con, rows)


def season_date_range(season: int) -> tuple[str, str]:
    return (f"{season}-03-01", f"{season}-11-30")


def ingest_seasons(
    con, fetch: FetchFn, seasons: list[int], players: pd.DataFrame | None = None
) -> int:
    total = 0
    for season in seasons:
        start, end = season_date_range(season)
        total += ingest_range(con, fetch, start, end, season, players=players)
    return total


def ingest_all(con, settings, *, fetchers: dict) -> dict[str, int]:
    """Run MLB ingest sources in dependency order, using only injected fetchers.

    `fetchers` maps source name -> the dependency needed to run that source;
    a source runs only if its key is present in `fetchers` (absent keys are
    skipped silently, so a caller/test can inject any subset without network
    access). Order: players -> games -> statcast -> fangraphs -> standings ->
    rollups. Seasons come from `settings.data.backfill_seasons`.

    Expected shape per key:
      "chadwick":  () -> pd.DataFrame                     (players.fetch_chadwick)
      "schedule":  (start_date, end_date) -> list[dict]    (statsapi_client.fetch_schedule)
      "statcast":  (season) -> pd.DataFrame                (statcast.fetch_statcast_season)
      "fangraphs": list[(table, fetch_fn, normalize_fn)]   (fangraphs.FANGRAPHS_SPECS)
      "standings": (season) -> dict                        (standings.fetch_standings)
      "rollups":   presence-only flag; value is not called (rollups are derived
                   from statcast_pitches already in the warehouse, not fetched)
    """
    from bblmlp.ingest.mlb.players import normalize_players
    from bblmlp.ingest.mlb.rollups import pitcher_game_stats, team_game_stats
    from bblmlp.ingest.mlb.standings import normalize_standings
    from bblmlp.ingest.mlb.statcast import normalize_statcast, write_statcast
    from bblmlp.storage import ensure_table_from_df

    seasons = settings.data.backfill_seasons
    counts: dict[str, int] = {}

    # 1. players — load once, keep the normalized df in memory to thread into
    # games below so probable-pitcher ids resolve.
    players_df: pd.DataFrame | None = None
    if "chadwick" in fetchers:
        players_df = normalize_players(fetchers["chadwick"]())
        counts["players"] = replace_all(con, "player_ids", players_df)

    # 2. games — per season, threading the players df for id resolution.
    if "schedule" in fetchers:
        counts["games"] = ingest_seasons(
            con, fetchers["schedule"], seasons, players=players_df
        )

    # 3. statcast — full season of pitch-level data per season.
    if "statcast" in fetchers:
        total = 0
        for season in seasons:
            raw = fetchers["statcast"](season)
            df = normalize_statcast(raw, season=season)
            total += write_statcast(con, df)
        counts["statcast"] = total

    # 4. fangraphs — four composite season tables per season.
    if "fangraphs" in fetchers:
        specs = fetchers["fangraphs"]
        total = 0
        for season in seasons:
            for table, fetch, normalize in specs:
                df = normalize(fetch(season), season=season)
                ensure_table_from_df(con, table, df)
                total += replace_partition(con, table, df, "season")
        counts["fangraphs"] = total

    # 5. standings — one table per season.
    if "standings" in fetchers:
        total = 0
        for season in seasons:
            raw = fetchers["standings"](season)
            df = normalize_standings(raw, season=season)
            total += replace_partition(con, "standings", df, "season")
        counts["standings"] = total

    # 6. rollups — derived from statcast_pitches already in the warehouse;
    # gated by presence only (no network fetch, so the dict value is unused).
    if "rollups" in fetchers:
        total = 0
        for season in seasons:
            pitches = con.execute(
                "SELECT * FROM statcast_pitches WHERE season = ?", [season]
            ).df()
            total += replace_partition(con, "pitcher_game_stats", pitcher_game_stats(pitches), "season")
            total += replace_partition(con, "team_game_stats", team_game_stats(pitches), "season")
        counts["rollups"] = total

    return counts
