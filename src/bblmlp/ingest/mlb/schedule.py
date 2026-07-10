"""Pure normalization of StatsAPI schedule dicts into Game rows."""
from __future__ import annotations


# Official StatsAPI statuses that mean the game is complete with a real result.
DECIDED_STATUSES = frozenset({"Final", "Completed Early"})


def compute_home_win(home_score, away_score, status) -> int | None:
    if status not in DECIDED_STATUSES or home_score is None or away_score is None:
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


def _resolve(players, full_name, season):
    if players is None or not full_name:
        return None
    parts = full_name.strip().split(" ", 1)
    if len(parts) != 2:
        return None
    from bblmlp.ingest.mlb.players import resolve_player_id

    return resolve_player_id(players, parts[0], parts[1], active_year=season)


def normalize_schedule(raw_games: list[dict], season: int, players=None) -> list[dict]:
    rows: list[dict] = []
    for raw in raw_games:
        home_score = raw.get("home_score")
        away_score = raw.get("away_score")
        status = raw.get("status")
        rows.append(
            {
                "game_pk": int(raw["game_id"]),
                "season": season,
                "game_type": raw.get("game_type"),
                # game_date is the authoritative day-level key (game_datetime is
                # UTC and tz-naive once stored).
                "game_date": _game_date(raw),
                "game_datetime": raw.get("game_datetime"),
                "home_team": raw.get("home_name"),
                "away_team": raw.get("away_name"),
                "home_team_id": raw.get("home_id"),
                "away_team_id": raw.get("away_id"),
                "home_probable_pitcher": raw.get("home_probable_pitcher") or None,
                "away_probable_pitcher": raw.get("away_probable_pitcher") or None,
                "home_probable_pitcher_id": _resolve(
                    players, raw.get("home_probable_pitcher") or "", season
                ),
                "away_probable_pitcher_id": _resolve(
                    players, raw.get("away_probable_pitcher") or "", season
                ),
                "venue": raw.get("venue_name"),
                "status": status,
                "home_score": home_score,
                "away_score": away_score,
                "home_win": compute_home_win(home_score, away_score, status),
            }
        )
    return rows
