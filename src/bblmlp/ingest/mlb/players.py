"""Chadwick player-id crosswalk: MLBAM <-> FanGraphs/BBRef/Retrosheet ids + names."""
from __future__ import annotations

import pandas as pd

_COLS = ["key_mlbam", "key_fangraphs", "key_bbref", "key_retro",
         "name_first", "name_last", "mlb_played_first", "mlb_played_last"]


def normalize_players(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    out = df[[c for c in _COLS if c in df.columns]].copy()
    out = out[out["key_mlbam"].notna()]
    out["key_mlbam"] = out["key_mlbam"].astype("int64")
    return out


def resolve_player_id(players: pd.DataFrame, name_first: str, name_last: str,
                      active_year: int | None = None) -> int | None:
    m = players[(players["name_first"].str.casefold() == name_first.casefold())
                & (players["name_last"].str.casefold() == name_last.casefold())]
    if active_year is not None and len(m) > 1:
        m = m[(m["mlb_played_first"] <= active_year)
              & (m["mlb_played_last"] >= active_year)]
    if len(m) == 1:
        return int(m["key_mlbam"].iloc[0])
    return None


def fetch_chadwick() -> pd.DataFrame:
    """Network call: pull the full Chadwick player-id register via pybaseball."""
    from pybaseball import chadwick_register

    return chadwick_register()
