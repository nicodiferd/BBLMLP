"""As-of trailing rolling-window bullpen features, partitioned by team
rather than individual pitcher identity -- a team's bullpen is a rotating
cast of relievers, not one pitcher's own trailing form (contrast
`features/rolling.py::pitcher_rolling_features`, which windows by pitcher
identity). Built on top of `bullpen_game_stats`
(`ingest/mlb/rollups.py`), itself an exact -- never starter-subtracted --
per-game aggregation of `pitcher_game_stats` rows where `is_starter ==
False`.

Same leakage guard and rate-reconstruction convention as
`features/rolling.py`: every feature for game N is computed only from
games strictly before N (`ROWS BETWEEN N PRECEDING AND 1 PRECEDING`), and
rates are sum(numerator)/sum(denominator) over the window, never a mean of
per-game rates.
"""
from __future__ import annotations

import duckdb
import pandas as pd

BULLPEN_WINDOWS: tuple[int, ...] = (10, 35, 75)


def bullpen_rolling_features(
    con: duckdb.DuckDBPyConnection,
    bullpen_game_stats: pd.DataFrame,
    games: pd.DataFrame,
) -> pd.DataFrame:
    window_cols = []
    for w in BULLPEN_WINDOWS:
        window_cols.append(f"""
            SUM(k) OVER w{w} / NULLIF(SUM(batters_faced) OVER w{w}, 0) AS k_pct_{w},
            SUM(bb) OVER w{w} / NULLIF(SUM(batters_faced) OVER w{w}, 0) AS bb_pct_{w},
            SUM(whiffs) OVER w{w} / NULLIF(SUM(pitches) OVER w{w}, 0) AS swstr_pct_{w},
            AVG(avg_velo) OVER w{w} AS avg_velo_{w},
            COUNT(*) OVER w{w} AS n_games_{w}
        """)
    window_defs = ",\n".join(
        f"w{w} AS (PARTITION BY team ORDER BY game_date, game_datetime, game_pk "
        f"ROWS BETWEEN {w} PRECEDING AND 1 PRECEDING)"
        for w in BULLPEN_WINDOWS
    )
    sql = f"""
        WITH base AS (
            SELECT b.game_pk, b.season, b.team,
                   b.pitches, b.batters_faced, b.k, b.bb, b.whiffs, b.avg_velo,
                   g.game_date, g.game_datetime
            FROM bullpen_game_stats_src b
            JOIN games_src g USING (game_pk)
        )
        SELECT game_pk, season, team,
            {",".join(window_cols)}
        FROM base
        WINDOW {window_defs}
        ORDER BY game_date, game_datetime, game_pk
    """
    con.register("bullpen_game_stats_src", bullpen_game_stats)
    con.register("games_src", games)
    try:
        return con.execute(sql).df()
    finally:
        con.unregister("bullpen_game_stats_src")
        con.unregister("games_src")
