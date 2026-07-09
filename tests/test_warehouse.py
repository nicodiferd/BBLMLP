import pytest

from bblmlp.storage import connect, init_schema, table_names, upsert_games


def _game(pk: int, home_win: int | None = None) -> dict:
    return {
        "game_pk": pk, "season": 2025, "game_date": "2025-07-04",
        "game_datetime": "2025-07-04T18:05:00Z", "home_team": "Dodgers",
        "away_team": "Giants", "home_team_id": 119, "away_team_id": 137,
        "home_probable_pitcher": "A B", "away_probable_pitcher": "C D",
        "venue": "Dodger Stadium", "status": "Final",
        "home_score": 5, "away_score": 3, "home_win": home_win,
    }


def test_init_schema_creates_tables(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    assert {"games", "statcast_pitches"}.issubset(table_names(con))


def test_upsert_games_is_idempotent(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    upsert_games(con, [_game(1, home_win=1)])
    upsert_games(con, [_game(1, home_win=1)])  # same pk again
    count = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    assert count == 1


def test_upsert_games_replaces_on_conflict(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    upsert_games(con, [_game(1, home_win=None)])   # scheduled, no result
    upsert_games(con, [_game(1, home_win=1)])       # later: final
    val = con.execute("SELECT home_win FROM games WHERE game_pk = 1").fetchone()[0]
    assert val == 1


def test_upsert_failure_rolls_back_and_connection_stays_usable(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    bad = _game(1)
    bad["season"] = None  # violates NOT NULL on season -> aborts the batch
    with pytest.raises(Exception):
        upsert_games(con, [bad])
    # the connection must remain usable for subsequent valid writes
    upsert_games(con, [_game(2, home_win=1)])
    count = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    assert count == 1  # bad batch rolled back (0), then one good row
