"""Statcast ingestion via pybaseball, normalized into statcast_pitches."""
from __future__ import annotations

import pandas as pd

from bblmlp.storage import replace_partition

STATCAST_COLUMNS = [
    # identity & context
    "game_pk", "game_date", "season", "game_type", "home_team", "away_team",
    "inning", "inning_topbot", "at_bat_number", "pitch_number",
    "pitcher", "batter", "player_name", "p_throws", "stand",
    # pitch
    "pitch_type", "pitch_name", "release_speed", "effective_speed",
    "release_spin_rate", "spin_axis", "release_pos_x", "release_pos_z",
    "release_extension", "pfx_x", "pfx_z", "plate_x", "plate_z", "zone",
    "type", "description", "sz_top", "sz_bot",
    # count / state
    "balls", "strikes", "outs_when_up", "on_1b", "on_2b", "on_3b",
    # outcome
    "events", "bb_type", "hit_location", "launch_speed", "launch_angle",
    "hit_distance_sc", "launch_speed_angle",
    # value
    "estimated_woba_using_speedangle", "estimated_ba_using_speedangle",
    "woba_value", "woba_denom", "babip_value", "iso_value",
    "delta_run_exp", "delta_home_win_exp",
    # score state
    "bat_score", "fld_score", "home_score", "away_score",
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
    # Idempotent at season granularity (the `ingest statcast --season` command
    # writes one full season per call): replace any existing rows for the
    # season(s) in this frame instead of appending duplicates.
    return replace_partition(con, "statcast_pitches", df, "season")


def fetch_statcast_season(season: int) -> pd.DataFrame:
    """Network call: pull a full season of Statcast via pybaseball."""
    from pybaseball import statcast

    return statcast(start_dt=f"{season}-03-01", end_dt=f"{season}-11-30")
