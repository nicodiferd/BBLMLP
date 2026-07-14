"""Statcast-derived per-game rollups: pitcher/team stats, starters, lineups.

Pure pandas aggregations over the widened `statcast_pitches` frame. These are
deterministic this-game aggregates only — no cross-game or time-window logic
(that belongs to a later as-of/rolling feature-builder service).
"""
from __future__ import annotations

import pandas as pd


def _fielding_team(df: pd.DataFrame) -> pd.Series:
    # Top of inning: away bats, home pitches. Bottom: home bats, away pitches.
    return df["home_team"].where(df["inning_topbot"] == "Top", df["away_team"])


def _batting_team(df: pd.DataFrame) -> pd.Series:
    return df["away_team"].where(df["inning_topbot"] == "Top", df["home_team"])


def pitcher_game_stats(pitches: pd.DataFrame) -> pd.DataFrame:
    df = pitches.copy()
    df["fld_team"] = _fielding_team(df)
    g = df.groupby(["game_pk", "season", "pitcher"], as_index=False)
    out = g.agg(
        team=("fld_team", "first"),
        pitches=("pitch_number", "size"),
        batters_faced=("at_bat_number", "nunique"),
        avg_velo=("release_speed", "mean"),
        xwoba_against=("estimated_woba_using_speedangle", "mean"),
    )
    # k / bb from per-PA terminal events
    ev = df.dropna(subset=["events"])
    k = ev[ev["events"] == "strikeout"].groupby(["game_pk", "pitcher"]).size()
    bb = ev[ev["events"] == "walk"].groupby(["game_pk", "pitcher"]).size()
    whiff = df[df["description"] == "swinging_strike"].groupby(["game_pk", "pitcher"]).size()
    out = out.set_index(["game_pk", "pitcher"])
    out["k"] = k
    out["bb"] = bb
    out["whiffs"] = whiff
    out[["k", "bb", "whiffs"]] = out[["k", "bb", "whiffs"]].fillna(0).astype(int)
    out["swstr_pct"] = out["whiffs"] / out["pitches"]
    out = out.reset_index()
    # starter = pitcher of the minimum at_bat_number faced by each fielding side
    first_ab = df.sort_values("at_bat_number").groupby(["game_pk", "fld_team"]).first().reset_index()
    starters = set(zip(first_ab["game_pk"], first_ab["pitcher"]))
    out["is_starter"] = [(gp, p) in starters for gp, p in zip(out["game_pk"], out["pitcher"])]
    return out


def bullpen_game_stats(pitcher_game_stats: pd.DataFrame) -> pd.DataFrame:
    """Exact per-game bullpen aggregation -- summed raw counts from relief
    appearances (`is_starter == False`), never a subtraction of starter
    totals from team totals. `avg_velo` is a pitch-weighted mean of each
    reliever's own (already-averaged) `avg_velo`, the same documented
    approximation pattern as team-grain `xwoba` in `features/rolling.py`.
    """
    df = pitcher_game_stats[~pitcher_game_stats["is_starter"]].copy()
    g = df.groupby(["game_pk", "season", "team"], as_index=False)
    out = g.agg(
        pitches=("pitches", "sum"),
        batters_faced=("batters_faced", "sum"),
        k=("k", "sum"),
        bb=("bb", "sum"),
        whiffs=("whiffs", "sum"),
        n_pitchers=("pitcher", "nunique"),
    )
    weighted_velo = (
        df.assign(_w=df["avg_velo"] * df["pitches"])
        .groupby(["game_pk", "season", "team"])["_w"]
        .sum()
    )
    out = out.set_index(["game_pk", "season", "team"])
    out["avg_velo"] = weighted_velo / out["pitches"]
    out["swstr_pct"] = out["whiffs"] / out["pitches"]
    return out.reset_index()


def lineup(pitches: pd.DataFrame) -> pd.DataFrame:
    df = pitches.copy()
    df["team"] = _batting_team(df)
    first = df.sort_values("at_bat_number").groupby(["game_pk", "team", "batter"], as_index=False)["at_bat_number"].min()
    first = first.sort_values(["game_pk", "team", "at_bat_number"])
    first["batting_order"] = first.groupby(["game_pk", "team"]).cumcount() + 1
    return first[["game_pk", "team", "batter", "batting_order"]]


def team_game_stats(pitches: pd.DataFrame) -> pd.DataFrame:
    df = pitches.copy()
    df["team"] = _batting_team(df)
    g = df.groupby(["game_pk", "season", "team"], as_index=False)
    out = g.agg(
        pa=("at_bat_number", "nunique"),
        xwoba=("estimated_woba_using_speedangle", "mean"),
    )
    ev = df.dropna(subset=["events"])
    k = ev[ev["events"] == "strikeout"].groupby(["game_pk", "team"]).size()
    bb = ev[ev["events"] == "walk"].groupby(["game_pk", "team"]).size()
    out = out.set_index(["game_pk", "team"])
    out["k_pct"] = (k / out["pa"]).fillna(0)
    out["bb_pct"] = (bb / out["pa"]).fillna(0)
    return out.reset_index()
