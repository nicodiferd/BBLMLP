"""Live daily lineups/probables ingestion via MLB-StatsAPI, flattened one row per player-slot."""
from __future__ import annotations

import pandas as pd


def normalize_live_lineups(raw_games: list[dict], game_date: str) -> pd.DataFrame:
    rows = []
    for g in raw_games:
        gid = g.get("game_id")
        for side, team_key in (("home", "home_name"), ("away", "away_name")):
            team = g.get(team_key)
            pp = g.get(f"{side}_probable_pitcher_id")
            if pp is not None:
                rows.append({"game_date": game_date, "game_pk": gid, "team": team,
                             "player_id": pp, "batting_order": None,
                             "is_probable_pitcher": True})
            for spot in g.get(f"{side}_lineup", []) or []:
                rows.append({"game_date": game_date, "game_pk": gid, "team": team,
                             "player_id": spot.get("player_id"),
                             "batting_order": spot.get("order"),
                             "is_probable_pitcher": False})
    return pd.DataFrame(rows)


def fetch_today_games(date: str) -> list[dict]:
    """Network call: pull today's schedule (with lineups/probables) via MLB-StatsAPI.

    Thin stub; enriching real posted lineups may need `statsapi.boxscore_data(game_pk)`
    per game to populate `{side}_lineup`. Not unit-tested.
    """
    import statsapi

    return statsapi.schedule(start_date=date, end_date=date)
