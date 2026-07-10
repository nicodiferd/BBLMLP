"""Standings ingestion via MLB-StatsAPI, normalized into one row per team."""
from __future__ import annotations

import pandas as pd


def normalize_standings(raw: dict, season: int) -> pd.DataFrame:
    rows = []
    for _div_id, div in raw.items():
        for t in div.get("teams", []):
            rows.append({
                "season": season,
                "team_id": t.get("team_id"),
                "team_name": t.get("name"),
                "w": t.get("w"), "l": t.get("l"),
                "win_pct": float(t["w"]) / max(1, (t.get("w", 0) + t.get("l", 0))),
                "gb": str(t.get("gb")),
                "div_rank": t.get("div_rank"),
                "streak": t.get("streak"),
                "runs_scored": t.get("runs_scored"),
                "runs_allowed": t.get("runs_allowed"),
            })
    return pd.DataFrame(rows)


def fetch_standings(season: int):
    """Network call: pull standings for a season via MLB-StatsAPI."""
    import statsapi

    return statsapi.standings_data(season=season)
