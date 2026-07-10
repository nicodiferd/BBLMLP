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


def _tidy_players(df: pd.DataFrame, season: int) -> pd.DataFrame:
    out = _tidy(df, season)  # snake_case + season
    if "idfg" in out.columns:
        out = out.rename(columns={"idfg": "key_fangraphs"})
    return out


def normalize_pitcher_stats(df: pd.DataFrame, season: int) -> pd.DataFrame:
    return _tidy_players(df, season)


def normalize_batter_stats(df: pd.DataFrame, season: int) -> pd.DataFrame:
    return _tidy_players(df, season)


def fetch_pitching_stats(season: int) -> pd.DataFrame:
    """Network call: pull individual pitcher season stats via pybaseball."""
    from pybaseball import pitching_stats

    return pitching_stats(season, season)


def fetch_batting_stats(season: int) -> pd.DataFrame:
    """Network call: pull individual batter season stats via pybaseball."""
    from pybaseball import batting_stats

    return batting_stats(season, season)
