"""FanGraphs team season tables (batting/pitching) via pybaseball."""
from __future__ import annotations

import re

import pandas as pd


def _snake(name: str) -> str:
    name = (
        name.replace("+", "_plus")
        .replace("%", "_pct")
        .replace("/", "_per_")
        .replace("-", "_minus")
    )
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    if name and name[0].isdigit():
        name = f"_{name}"
    return name


def _tidy(df: pd.DataFrame, season: int) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_snake(c) for c in df.columns]
    df["season"] = season
    return df


def normalize_team_batting(df: pd.DataFrame, season: int) -> pd.DataFrame:
    return _tidy(df, season)


def normalize_team_pitching(df: pd.DataFrame, season: int) -> pd.DataFrame:
    return _tidy(df, season)


def fetch_team_batting(season: int) -> pd.DataFrame:
    """Network call: pull team batting season stats via pybaseball."""
    from pybaseball import team_batting

    return team_batting(season)


def fetch_team_pitching(season: int) -> pd.DataFrame:
    """Network call: pull team pitching season stats via pybaseball."""
    from pybaseball import team_pitching

    return team_pitching(season)
