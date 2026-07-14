"""As-of trailing rolling-window features over the Statcast-derived rollup
tables (`team_game_stats`, `pitcher_game_stats`).

Every feature for game N is computed only from games strictly before N
(`ROWS BETWEEN N PRECEDING AND 1 PRECEDING`) -- never game N itself. Rates
are reconstructed as sum(numerator)/sum(denominator) over the window, never
a mean of already-computed per-game rates.

At team grain, `xwoba` is a documented approximation: `team_game_stats`
stores a per-game mean over batted-ball events, not a batted-ball count, so
there is no exact denominator to reconstruct against. It is PA-weighted
(`sum(xwoba * pa) / sum(pa)`) as the closest available proxy -- unlike
`k_pct`/`bb_pct`, which reconstruct exactly this way since `k_pct * pa`
recovers the true strikeout count. A precise fix would persist a
batted-ball count in `rollups.py::team_game_stats`; that's a deliberate
fast-follow, not done here.

Cold start (partial windows) is intentionally left as DuckDB computes it
naturally -- fewer rows early, NULL only with zero prior games. Shrinkage
toward a prior is a separate, later concern.
"""
from __future__ import annotations

import duckdb
import pandas as pd

TEAM_WINDOWS: tuple[int, ...] = (30, 162)


def team_rolling_features(
    con: duckdb.DuckDBPyConnection,
    team_game_stats: pd.DataFrame,
    games: pd.DataFrame,
) -> pd.DataFrame:
    window_cols = []
    for w in TEAM_WINDOWS:
        window_cols.append(f"""
            SUM(k_pct * pa) OVER w{w} / NULLIF(SUM(pa) OVER w{w}, 0) AS k_pct_{w},
            SUM(bb_pct * pa) OVER w{w} / NULLIF(SUM(pa) OVER w{w}, 0) AS bb_pct_{w},
            SUM(xwoba * pa) OVER w{w} / NULLIF(SUM(pa) OVER w{w}, 0) AS xwoba_{w},
            COUNT(*) OVER w{w} AS n_games_{w}
        """)
    window_defs = ",\n".join(
        f"w{w} AS (PARTITION BY team ORDER BY game_date, game_datetime, game_pk "
        f"ROWS BETWEEN {w} PRECEDING AND 1 PRECEDING)"
        for w in TEAM_WINDOWS
    )
    sql = f"""
        WITH base AS (
            SELECT t.game_pk, t.season, t.team, t.pa, t.xwoba, t.k_pct, t.bb_pct,
                   g.game_date, g.game_datetime
            FROM team_game_stats_src t
            JOIN games_src g USING (game_pk)
        )
        SELECT game_pk, season, team,
            {",".join(window_cols)}
        FROM base
        WINDOW {window_defs}
        ORDER BY game_date, game_datetime, game_pk
    """
    con.register("team_game_stats_src", team_game_stats)
    con.register("games_src", games)
    try:
        return con.execute(sql).df()
    finally:
        con.unregister("team_game_stats_src")
        con.unregister("games_src")
