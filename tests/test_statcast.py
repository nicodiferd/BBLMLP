import pandas as pd

from bblmlp.ingest.mlb.statcast import normalize_statcast, write_statcast
from bblmlp.storage import connect, init_schema


def _raw_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "game_pk": [745123, 745123, None],
            "game_date": ["2024-07-04", "2024-07-04", "2024-07-04"],
            "pitcher": [111, 111, 222],
            "batter": [333, 444, 555],
            "events": ["strikeout", None, "single"],
            "description": ["swinging_strike", "ball", "hit_into_play"],
            "pitch_type": ["FF", "SL", "CH"],
            "release_speed": [95.1, 84.3, 82.0],
            "estimated_woba_using_speedangle": [0.0, None, 0.45],
            "at_bat_number": [1, 1, 2],
            "pitch_number": [3, 1, 1],
            "extra_col_ignored": ["a", "b", "c"],
        }
    )


def test_normalize_drops_null_game_pk_and_adds_season():
    out = normalize_statcast(_raw_df(), season=2024)
    assert (out["season"] == 2024).all()
    assert out["game_pk"].notna().all()
    assert len(out) == 2  # null game_pk row dropped
    assert "extra_col_ignored" not in out.columns


def test_write_statcast_appends_rows(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    out = normalize_statcast(_raw_df(), season=2024)
    n = write_statcast(con, out)
    assert n == 2
    total = con.execute("SELECT COUNT(*) FROM statcast_pitches").fetchone()[0]
    assert total == 2


def test_write_statcast_is_idempotent(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    out = normalize_statcast(_raw_df(), season=2024)
    write_statcast(con, out)
    write_statcast(con, out)  # same season again
    total = con.execute("SELECT COUNT(*) FROM statcast_pitches").fetchone()[0]
    assert total == 2  # replaced per season, not doubled


def test_normalize_keeps_handedness_count_and_value_columns():
    raw = pd.DataFrame({
        "game_pk": [1], "game_date": ["2024-04-01"], "pitcher": [111], "batter": [222],
        "events": ["strikeout"], "description": ["swinging_strike"], "pitch_type": ["FF"],
        "release_speed": [95.1], "estimated_woba_using_speedangle": [0.20],
        "at_bat_number": [1], "pitch_number": [3],
        "stand": ["R"], "p_throws": ["L"], "balls": [1], "strikes": [2],
        "launch_speed": [88.0], "launch_angle": [12.0], "woba_value": [0.0],
        "delta_run_exp": [-0.1], "inning": [1], "inning_topbot": ["Top"],
        "home_team": ["SF"], "away_team": ["COL"],
    })
    out = normalize_statcast(raw, season=2024)
    for col in ["stand", "p_throws", "balls", "strikes", "launch_speed",
                "delta_run_exp", "inning_topbot", "home_team", "season"]:
        assert col in out.columns
    assert out["season"].iloc[0] == 2024
    assert out["game_pk"].dtype == "int64"
