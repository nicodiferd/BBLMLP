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
