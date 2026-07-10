"""FanGraphs season tables via the FanGraphs JSON API.

pybaseball's team/player leaderboard functions scrape the deprecated
`leaders-legacy.aspx` endpoint, which now returns 403 (FanGraphs killed it and
fronts the site with Cloudflare). We hit the current FanGraphs JSON leaderboard
API instead, using curl_cffi's Chrome TLS impersonation to pass the Cloudflare
bot check (a plain requests call is blocked regardless of headers).
"""
from __future__ import annotations

import re

import pandas as pd

_FG_API = "https://www.fangraphs.com/api/leaders/major-league/data"


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


def _dedupe(cols: list[str]) -> list[str]:
    """Make snake-cased column names unique. The FanGraphs API returns a very
    wide (~500-col) schema where distinct source labels can snake to the same
    name; a duplicate column name would break the DuckDB INSERT."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for c in cols:
        if c in seen:
            seen[c] += 1
            out.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            out.append(c)
    return out


def _tidy(df: pd.DataFrame, season: int) -> pd.DataFrame:
    df = df.copy()
    df.columns = _dedupe([_snake(c) for c in df.columns])
    df["season"] = season
    return df


def normalize_team_batting(df: pd.DataFrame, season: int) -> pd.DataFrame:
    return _tidy(df, season)


def normalize_team_pitching(df: pd.DataFrame, season: int) -> pd.DataFrame:
    return _tidy(df, season)


def _fg_fetch(stats: str, season: int, *, ind: str, team: str = "0") -> pd.DataFrame:
    """Network call: FanGraphs leaderboard JSON API via Chrome TLS impersonation.

    `stats`='bat'|'pit'; `ind`='0' aggregates (team totals) / '1' per player;
    `team`='0,ts' groups by team for the team tables.
    """
    from curl_cffi import requests as cr

    params = {
        "pos": "all", "stats": stats, "lg": "all", "qual": "0", "type": "8",
        "season": str(season), "season1": str(season), "ind": ind,
        "team": team, "pageitems": "100000", "pagenum": "1",
    }
    r = cr.get(_FG_API, params=params, impersonate="chrome", timeout=90)
    r.raise_for_status()
    df = pd.DataFrame(r.json().get("data", []))
    # The API wraps Team (and player Name) in an HTML <a> link; strip tags so
    # `team` is a clean abbreviation usable as a join key.
    for col in ("Team", "TeamName", "Name", "PlayerName"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace(r"<[^>]+>", "", regex=True)
    # Match the id column pybaseball produced so the crosswalk join stays stable.
    if "playerid" in df.columns:
        df = df.rename(columns={"playerid": "IDfg"})
    return df


def fetch_team_batting(season: int) -> pd.DataFrame:
    return _fg_fetch("bat", season, ind="0", team="0,ts")


def fetch_team_pitching(season: int) -> pd.DataFrame:
    return _fg_fetch("pit", season, ind="0", team="0,ts")


def _tidy_players(df: pd.DataFrame, season: int) -> pd.DataFrame:
    out = _tidy(df, season)  # snake_case + dedupe + season
    if "idfg" in out.columns:
        out = out.rename(columns={"idfg": "key_fangraphs"})
    return out


def normalize_pitcher_stats(df: pd.DataFrame, season: int) -> pd.DataFrame:
    return _tidy_players(df, season)


def normalize_batter_stats(df: pd.DataFrame, season: int) -> pd.DataFrame:
    return _tidy_players(df, season)


def fetch_pitching_stats(season: int) -> pd.DataFrame:
    return _fg_fetch("pit", season, ind="1")


def fetch_batting_stats(season: int) -> pd.DataFrame:
    return _fg_fetch("bat", season, ind="1")


# (table_name, fetch_fn, normalize_fn) for each of the four FanGraphs season
# tables. Shared by the `ingest fangraphs` CLI command and the `ingest_all`
# orchestrator so the composite-write loop (ensure_table_from_df +
# replace_partition per table) is defined in exactly one place.
FANGRAPHS_SPECS = [
    ("team_batting_season", fetch_team_batting, normalize_team_batting),
    ("team_pitching_season", fetch_team_pitching, normalize_team_pitching),
    ("pitcher_stats_season", fetch_pitching_stats, normalize_pitcher_stats),
    ("batter_stats_season", fetch_batting_stats, normalize_batter_stats),
]
