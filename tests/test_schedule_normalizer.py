import json
from pathlib import Path

from bblmlp.ingest.mlb.schedule import compute_home_win, normalize_schedule

RAW = json.loads(Path("tests/fixtures/statsapi_schedule.json").read_text())


def test_normalize_returns_game_rows_with_required_keys():
    rows = normalize_schedule(RAW, season=2024)
    assert len(rows) == len(RAW)
    required = {
        "game_pk", "season", "game_type", "game_date", "home_team", "away_team",
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


def test_compute_home_win_completed_early_counts():
    assert compute_home_win(12, 3, "Completed Early") == 1
    assert compute_home_win(3, 12, "Completed Early") == 0


def test_normalizer_labels_completed_early_game():
    early = [g for g in RAW if g.get("status") == "Completed Early"]
    assert early, "fixture should contain a Completed Early game"
    rows = normalize_schedule(RAW, season=2024)
    by_pk = {r["game_pk"]: r for r in rows}
    for g in early:
        row = by_pk[int(g["game_id"])]
        if g["home_score"] == g["away_score"]:
            expected = None
        else:
            expected = 1 if g["home_score"] > g["away_score"] else 0
        assert row["home_win"] == expected
        assert row["home_win"] is not None  # a decided game must be labeled
