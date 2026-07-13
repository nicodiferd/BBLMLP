import duckdb
import pytest

from bblmlp.storage import (
    append_rows,
    connect,
    ensure_table_from_df,
    init_schema,
    replace_all,
    replace_partition,
    table_names,
    upsert_games,
)


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


def test_writers_quote_reserved_word_columns():
    # FanGraphs' wide schema includes columns that snake to SQL reserved words
    # (e.g. `positional`, `order`); the writers must quote identifiers.
    import pandas as pd

    con = duckdb.connect(":memory:")
    df = pd.DataFrame({"season": [2024], "positional": [1.5], "order": [2], "war": [3.1]})
    ensure_table_from_df(con, "fg", df)
    assert replace_partition(con, "fg", df, "season") == 1
    assert replace_partition(con, "fg", df, "season") == 1  # idempotent rerun
    assert con.execute("SELECT count(*) FROM fg").fetchone()[0] == 1
    assert replace_all(con, "fg", df) == 1


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


def _mk(con):
    con.execute("CREATE TABLE t (season INTEGER, v INTEGER)")


def test_replace_partition_is_idempotent():
    con = duckdb.connect(":memory:")
    _mk(con)
    import pandas as pd
    df = pd.DataFrame({"season": [2024, 2024], "v": [1, 2]})
    assert replace_partition(con, "t", df, "season") == 2
    assert replace_partition(con, "t", df, "season") == 2  # rerun
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 2  # no dupes
    assert con.execute("SELECT count(*) FROM t WHERE season=2023").fetchone()[0] == 0


def test_replace_partition_leaves_other_partitions():
    con = duckdb.connect(":memory:")
    _mk(con)
    import pandas as pd
    replace_partition(con, "t", pd.DataFrame({"season":[2023],"v":[9]}), "season")
    replace_partition(con, "t", pd.DataFrame({"season":[2024],"v":[1]}), "season")
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 2


def test_replace_all_truncates():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE p (id INTEGER)")
    import pandas as pd
    replace_all(con, "p", pd.DataFrame({"id":[1,2,3]}))
    replace_all(con, "p", pd.DataFrame({"id":[9]}))
    assert con.execute("SELECT count(*) FROM p").fetchone()[0] == 1


def test_ensure_table_from_df_creates_empty_table_matching_schema():
    con = duckdb.connect(":memory:")
    import pandas as pd
    df = pd.DataFrame({"season": [2024], "team": ["SFG"], "wrc_plus": [105]})
    ensure_table_from_df(con, "fg_team_batting", df)
    assert "fg_team_batting" in table_names(con)
    assert con.execute("SELECT count(*) FROM fg_team_batting").fetchone()[0] == 0
    cols = [r[0] for r in con.execute("DESCRIBE fg_team_batting").fetchall()]
    assert cols == ["season", "team", "wrc_plus"]


def test_ensure_table_from_df_is_a_noop_if_table_already_exists():
    con = duckdb.connect(":memory:")
    import pandas as pd
    df = pd.DataFrame({"season": [2024], "v": [1]})
    ensure_table_from_df(con, "t2", df)
    replace_partition(con, "t2", df, "season")
    ensure_table_from_df(con, "t2", df)  # should not wipe existing rows
    assert con.execute("SELECT count(*) FROM t2").fetchone()[0] == 1


def test_init_schema_creates_kalshi_quotes_table(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    assert "kalshi_quotes" in table_names(con)


def test_append_rows_accumulates_rather_than_replaces():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE q (pulled_at VARCHAR, v INTEGER)")
    import pandas as pd
    assert append_rows(con, "q", pd.DataFrame({"pulled_at": ["t1"], "v": [1]})) == 1
    assert append_rows(con, "q", pd.DataFrame({"pulled_at": ["t2"], "v": [2]})) == 1
    assert con.execute("SELECT count(*) FROM q").fetchone()[0] == 2  # both pulls kept


def test_append_rows_empty_dataframe_is_a_noop():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE q (v INTEGER)")
    import pandas as pd
    assert append_rows(con, "q", pd.DataFrame({"v": []})) == 0
    assert con.execute("SELECT count(*) FROM q").fetchone()[0] == 0
