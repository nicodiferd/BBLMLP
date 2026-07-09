import json
from pathlib import Path

from bblmlp.ingest.mlb.schedule import compute_home_win, normalize_schedule

RAW = json.loads(Path("tests/fixtures/statsapi_schedule.json").read_text())


def test_normalize_returns_game_rows_with_required_keys():
    rows = normalize_schedule(RAW, season=2024)
    assert len(rows) == len(RAW)
    required = {
        "game_pk", "season", "game_date", "home_team", "away_team",
        "home_team_id", "away_team_id", "status", "home_score",
        "away_score", "home_win",
    }
    for row in rows:
        assert required.issubset(row.keys())
        assert row["season"] == 2024
        assert isinstance(row["game_pk"], int)


def test_compute_home_win_decided_final():
    assert compute_home_win(5, 3, "Final") == 1
    assert compute_home_win(2, 6, "Final") == 0


def test_compute_home_win_unplayed_or_tie_is_none():
    assert compute_home_win(None, None, "Scheduled") is None
    assert compute_home_win(4, 4, "Final") is None  # tie => undecided
    assert compute_home_win(5, 3, "Scheduled") is None
