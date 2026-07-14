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
    team_crosswalk -> rollups. Seasons come from `settings.data.backfill_seasons`.

    Expected shape per key:
      "chadwick":       () -> pd.DataFrame                  (players.fetch_chadwick)
      "schedule":       (start_date, end_date) -> list[dict] (statsapi_client.fetch_schedule)
      "statcast":       (season) -> pd.DataFrame             (statcast.fetch_statcast_season)
      "fangraphs":      list[(table, fetch_fn, normalize_fn)] (fangraphs.FANGRAPHS_SPECS)
      "standings":      (season) -> dict                     (standings.fetch_standings)
      "team_crosswalk": presence-only flag; value is not called (derived from
                        standings/games/statcast_pitches/team_batting_season
                        already in the warehouse, not fetched)
      "rollups":        presence-only flag; value is not called (rollups are derived
                        from statcast_pitches already in the warehouse, not fetched)
    """
    from bblmlp.ingest.mlb.players import normalize_players
    from bblmlp.ingest.mlb.rollups import bullpen_game_stats, pitcher_game_stats, team_game_stats
    from bblmlp.ingest.mlb.standings import normalize_standings
    from bblmlp.ingest.mlb.statcast import normalize_statcast, write_statcast
    from bblmlp.ingest.mlb.team_crosswalk import build_team_crosswalk
    from bblmlp.storage import ensure_table_from_df, table_names

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

    # 6. team_crosswalk — reconciles team_id against Statcast/FanGraphs
    # abbreviations; derived from tables already in the warehouse, gated by
    # presence only (no network fetch, so the dict value is unused).
    if "team_crosswalk" in fetchers:
        total = 0
        has_fangraphs_table = "team_batting_season" in table_names(con)
        for season in seasons:
            standings_df = con.execute(
                "SELECT season, team_id, team_name FROM standings WHERE season = ?", [season]
            ).df()
            games_df = con.execute(
                "SELECT game_pk, season, game_type, home_team_id, away_team_id FROM games WHERE season = ?",
                [season],
            ).df()
            statcast_df = con.execute(
                "SELECT game_pk, home_team, away_team FROM statcast_pitches WHERE season = ?", [season]
            ).df()
            if has_fangraphs_table:
                fangraphs_df = con.execute(
                    "SELECT season, team FROM team_batting_season WHERE season = ?", [season]
                ).df()
            else:
                fangraphs_df = pd.DataFrame(columns=["season", "team"])
            crosswalk_df = build_team_crosswalk(standings_df, games_df, statcast_df, fangraphs_df)
            total += replace_partition(con, "team_crosswalk", crosswalk_df, "season")
        counts["team_crosswalk"] = total

    # 7. rollups — derived from statcast_pitches already in the warehouse;
    # gated by presence only (no network fetch, so the dict value is unused).
    if "rollups" in fetchers:
        total = 0
        for season in seasons:
            pitches = con.execute(
                "SELECT * FROM statcast_pitches WHERE season = ?", [season]
            ).df()
            pitcher_game_stats_df = pitcher_game_stats(pitches)
            total += replace_partition(con, "pitcher_game_stats", pitcher_game_stats_df, "season")
            total += replace_partition(con, "team_game_stats", team_game_stats(pitches), "season")
            total += replace_partition(
                con, "bullpen_game_stats", bullpen_game_stats(pitcher_game_stats_df), "season"
            )
        counts["rollups"] = total

    return counts
