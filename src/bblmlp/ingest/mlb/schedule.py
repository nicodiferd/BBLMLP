"""Pure normalization of StatsAPI schedule dicts into Game rows."""
from __future__ import annotations


def compute_home_win(home_score, away_score, status) -> int | None:
    if status != "Final" or home_score is None or away_score is None:
        return None
    if home_score == away_score:
        return None
    return 1 if home_score > away_score else 0


def _game_date(raw: dict) -> str:
    # statsapi provides "game_date" (YYYY-MM-DD); fall back to datetime prefix.
    if raw.get("game_date"):
        return str(raw["game_date"])
    dt = raw.get("game_datetime") or ""
    return dt[:10]


def normalize_schedule(raw_games: list[dict], season: int) -> list[dict]:
    rows: list[dict] = []
    for raw in raw_games:
        home_score = raw.get("home_score")
        away_score = raw.get("away_score")
        status = raw.get("status")
        rows.append(
            {
                "game_pk": int(raw["game_id"]),
                "season": season,
                "game_date": _game_date(raw),
                "game_datetime": raw.get("game_datetime"),
                "home_team": raw.get("home_name"),
                "away_team": raw.get("away_name"),
                "home_team_id": raw.get("home_id"),
                "away_team_id": raw.get("away_id"),
                "home_probable_pitcher": raw.get("home_probable_pitcher") or None,
                "away_probable_pitcher": raw.get("away_probable_pitcher") or None,
                "venue": raw.get("venue_name"),
                "status": status,
                "home_score": home_score,
                "away_score": away_score,
                "home_win": compute_home_win(home_score, away_score, status),
            }
        )
    return rows
