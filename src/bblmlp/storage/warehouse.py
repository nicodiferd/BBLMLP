"""DuckDB warehouse: connection, schema, and idempotent writes."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

GAMES_DDL = """
CREATE TABLE IF NOT EXISTS games (
    game_pk BIGINT PRIMARY KEY,
    season INTEGER NOT NULL,
    game_type VARCHAR,
    game_date DATE NOT NULL,
    game_datetime TIMESTAMP,
    home_team VARCHAR NOT NULL,
    away_team VARCHAR NOT NULL,
    home_team_id INTEGER,
    away_team_id INTEGER,
    home_probable_pitcher VARCHAR,
    away_probable_pitcher VARCHAR,
    home_probable_pitcher_id INTEGER,
    away_probable_pitcher_id INTEGER,
    venue VARCHAR,
    status VARCHAR,
    home_score INTEGER,
    away_score INTEGER,
    home_win INTEGER
);
"""

STATCAST_DDL = """
CREATE TABLE IF NOT EXISTS statcast_pitches (
    -- identity & context
    game_pk BIGINT,
    game_date DATE,
    season INTEGER,
    game_type VARCHAR,
    home_team VARCHAR,
    away_team VARCHAR,
    inning INTEGER,
    inning_topbot VARCHAR,
    at_bat_number INTEGER,
    pitch_number INTEGER,
    pitcher INTEGER,
    batter INTEGER,
    player_name VARCHAR,
    p_throws VARCHAR,
    stand VARCHAR,
    -- pitch
    pitch_type VARCHAR,
    pitch_name VARCHAR,
    release_speed DOUBLE,
    effective_speed DOUBLE,
    release_spin_rate DOUBLE,
    spin_axis DOUBLE,
    release_pos_x DOUBLE,
    release_pos_z DOUBLE,
    release_extension DOUBLE,
    pfx_x DOUBLE,
    pfx_z DOUBLE,
    plate_x DOUBLE,
    plate_z DOUBLE,
    zone DOUBLE,
    type VARCHAR,
    description VARCHAR,
    sz_top DOUBLE,
    sz_bot DOUBLE,
    -- count / state
    balls INTEGER,
    strikes INTEGER,
    outs_when_up INTEGER,
    on_1b DOUBLE,
    on_2b DOUBLE,
    on_3b DOUBLE,
    -- outcome
    events VARCHAR,
    bb_type VARCHAR,
    hit_location DOUBLE,
    launch_speed DOUBLE,
    launch_angle DOUBLE,
    hit_distance_sc DOUBLE,
    launch_speed_angle DOUBLE,
    -- value
    estimated_woba_using_speedangle DOUBLE,
    estimated_ba_using_speedangle DOUBLE,
    woba_value DOUBLE,
    woba_denom DOUBLE,
    babip_value DOUBLE,
    iso_value DOUBLE,
    delta_run_exp DOUBLE,
    delta_home_win_exp DOUBLE,
    -- score state
    bat_score INTEGER,
    fld_score INTEGER,
    home_score INTEGER,
    away_score INTEGER
);
"""

PLAYER_IDS_DDL = """
CREATE TABLE IF NOT EXISTS player_ids (
    key_mlbam BIGINT PRIMARY KEY,
    key_fangraphs BIGINT,
    key_bbref VARCHAR,
    key_retro VARCHAR,
    name_first VARCHAR,
    name_last VARCHAR,
    mlb_played_first INTEGER,
    mlb_played_last INTEGER
);
"""

PITCHER_GAME_DDL = """
CREATE TABLE IF NOT EXISTS pitcher_game_stats (
    game_pk BIGINT,
    pitcher INTEGER,
    season INTEGER,
    pitches INTEGER,
    batters_faced INTEGER,
    avg_velo DOUBLE,
    xwoba_against DOUBLE,
    k INTEGER,
    bb INTEGER,
    whiffs INTEGER,
    csw_pct DOUBLE,
    is_starter BOOLEAN
);
"""

TEAM_GAME_DDL = """
CREATE TABLE IF NOT EXISTS team_game_stats (
    game_pk BIGINT,
    team VARCHAR,
    season INTEGER,
    pa INTEGER,
    xwoba DOUBLE,
    k_pct DOUBLE,
    bb_pct DOUBLE
);
"""

STANDINGS_DDL = """
CREATE TABLE IF NOT EXISTS standings (
    season INTEGER,
    team_id INTEGER,
    team_name VARCHAR,
    w INTEGER,
    l INTEGER,
    win_pct DOUBLE,
    gb VARCHAR,
    div_rank VARCHAR,
    streak VARCHAR,
    runs_scored INTEGER,
    runs_allowed INTEGER
);
"""

_GAME_COLUMNS = [
    "game_pk", "season", "game_type", "game_date", "game_datetime", "home_team", "away_team",
    "home_team_id", "away_team_id", "home_probable_pitcher", "away_probable_pitcher",
    "home_probable_pitcher_id", "away_probable_pitcher_id",
    "venue", "status", "home_score", "away_score", "home_win",
]


def connect(path: str | Path) -> duckdb.DuckDBPyConnection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(p))


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(GAMES_DDL)
    con.execute(STATCAST_DDL)
    con.execute(PLAYER_IDS_DDL)
    con.execute(PITCHER_GAME_DDL)
    con.execute(TEAM_GAME_DDL)
    con.execute(STANDINGS_DDL)


def table_names(con: duckdb.DuckDBPyConnection) -> set[str]:
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {r[0] for r in rows}


def replace_partition(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame, part_col: str) -> int:
    """Delete all rows whose part_col value appears in df, then insert df. Idempotent."""
    if df is None or len(df) == 0:
        return 0
    parts = list(dict.fromkeys(df[part_col].tolist()))
    cols = ", ".join(df.columns)
    con.register("_df_repl", df)
    try:
        con.execute("BEGIN TRANSACTION")
        try:
            ph = ", ".join(["?"] * len(parts))
            con.execute(f"DELETE FROM {table} WHERE {part_col} IN ({ph})", parts)
            con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _df_repl")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.unregister("_df_repl")
    return len(df)


def ensure_table_from_df(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> None:
    """Create `table` from df's schema if it doesn't exist yet (no rows copied).

    Used for wide, year-varying FanGraphs frames where a fixed DDL in
    `init_schema` would be brittle; the writer creates the table on demand
    from the first normalized DataFrame it sees.
    """
    con.register("_tmpl", df)
    con.execute(f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM _tmpl LIMIT 0")
    con.unregister("_tmpl")


def replace_all(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> int:
    """Truncate table and insert df. Idempotent (full replace)."""
    if df is None or len(df) == 0:
        return 0
    cols = ", ".join(df.columns)
    con.register("_df_all", df)
    try:
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(f"DELETE FROM {table}")
            con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _df_all")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.unregister("_df_all")
    return len(df)


def upsert_games(con: duckdb.DuckDBPyConnection, rows: list[dict]) -> int:
    if not rows:
        return 0
    placeholders = ", ".join(["?"] * len(_GAME_COLUMNS))
    cols = ", ".join(_GAME_COLUMNS)
    con.execute("BEGIN TRANSACTION")
    try:
        con.executemany(
            f"INSERT OR REPLACE INTO games ({cols}) VALUES ({placeholders})",
            [[r.get(c) for c in _GAME_COLUMNS] for r in rows],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(rows)
