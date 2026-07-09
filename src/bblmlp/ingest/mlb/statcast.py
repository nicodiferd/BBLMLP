"""Statcast ingestion via pybaseball, normalized into statcast_pitches."""
from __future__ import annotations

import pandas as pd

STATCAST_COLUMNS = [
    "game_pk", "game_date", "season", "pitcher", "batter", "events",
    "description", "pitch_type", "release_speed",
    "estimated_woba_using_speedangle", "at_bat_number", "pitch_number",
]


def normalize_statcast(df: pd.DataFrame, season: int) -> pd.DataFrame:
    df = df.copy()
    df["season"] = season
    df = df[df["game_pk"].notna()]
    keep = [c for c in STATCAST_COLUMNS if c in df.columns]
    out = df[keep].copy()
    out["game_pk"] = out["game_pk"].astype("int64")
    return out


def write_statcast(con, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    con.register("df_statcast", df)
    cols = ", ".join(df.columns)
    con.execute(f"INSERT INTO statcast_pitches ({cols}) SELECT {cols} FROM df_statcast")
    con.unregister("df_statcast")
    return len(df)


def fetch_statcast_season(season: int) -> pd.DataFrame:
    """Network call: pull a full season of Statcast via pybaseball."""
    from pybaseball import statcast

    return statcast(start_dt=f"{season}-03-01", end_dt=f"{season}-11-30")
