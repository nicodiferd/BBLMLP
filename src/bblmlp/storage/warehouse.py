"""DuckDB warehouse: connection, schema, and idempotent writes."""
from __future__ import annotations

from pathlib import Path

import duckdb

GAMES_DDL = """
CREATE TABLE IF NOT EXISTS games (
    game_pk BIGINT PRIMARY KEY,
    season INTEGER NOT NULL,
    game_date DATE NOT NULL,
    game_datetime TIMESTAMP,
    home_team VARCHAR NOT NULL,
    away_team VARCHAR NOT NULL,
    home_team_id INTEGER,
    away_team_id INTEGER,
    home_probable_pitcher VARCHAR,
    away_probable_pitcher VARCHAR,
    venue VARCHAR,
    status VARCHAR,
    home_score INTEGER,
    away_score INTEGER,
    home_win INTEGER
);
"""

STATCAST_DDL = """
CREATE TABLE IF NOT EXISTS statcast_pitches (
    game_pk BIGINT,
    game_date DATE,
    season INTEGER,
    pitcher INTEGER,
    batter INTEGER,
    events VARCHAR,
    description VARCHAR,
    pitch_type VARCHAR,
    release_speed DOUBLE,
    estimated_woba_using_speedangle DOUBLE,
    at_bat_number INTEGER,
    pitch_number INTEGER
);
"""

_GAME_COLUMNS = [
    "game_pk", "season", "game_date", "game_datetime", "home_team", "away_team",
    "home_team_id", "away_team_id", "home_probable_pitcher", "away_probable_pitcher",
    "venue", "status", "home_score", "away_score", "home_win",
]


def connect(path: str | Path) -> duckdb.DuckDBPyConnection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(p))


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(GAMES_DDL)
    con.execute(STATCAST_DDL)


def table_names(con: duckdb.DuckDBPyConnection) -> set[str]:
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {r[0] for r in rows}


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
