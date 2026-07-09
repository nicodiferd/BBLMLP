"""Elo / Bradley-Terry baseline for pre-game P(home_win).

Ratings update chronologically (game_date, then game_pk as tiebreak), so the
probability attached to each game uses only information available before it
was played. All functions are pure: the input DataFrame is never mutated.
"""

from __future__ import annotations

import pandas as pd


def _elo_pass(
    games: pd.DataFrame,
    k: float,
    home_adv: float,
    initial: float,
    scale: float,
) -> tuple[pd.Series, dict[str, float]]:
    ordered = games.sort_values(["game_date", "game_pk"], kind="stable")
    ratings: dict[str, float] = {}
    probs: list[float] = []
    for home, away, outcome in zip(
        ordered["home_team"], ordered["away_team"], ordered["home_win"]
    ):
        r_home = ratings.get(home, initial)
        r_away = ratings.get(away, initial)
        p_home = 1.0 / (1.0 + 10.0 ** (-((r_home + home_adv) - r_away) / scale))
        probs.append(p_home)
        delta = k * (outcome - p_home)
        ratings[home] = r_home + delta
        ratings[away] = r_away - delta
    return pd.Series(probs, index=ordered.index, name="p_home_elo"), ratings


def elo_probabilities(
    games: pd.DataFrame,
    *,
    k: float = 20.0,
    home_adv: float = 30.0,
    initial: float = 1500.0,
    scale: float = 400.0,
) -> pd.Series:
    """Pre-game P(home_win) for every row, aligned to the input index."""
    probs, _ = _elo_pass(games, k, home_adv, initial, scale)
    return probs.reindex(games.index)


def final_elo_ratings(
    games: pd.DataFrame,
    *,
    k: float = 20.0,
    home_adv: float = 30.0,
    initial: float = 1500.0,
    scale: float = 400.0,
) -> dict[str, float]:
    """Ratings after processing every game, keyed by team."""
    _, ratings = _elo_pass(games, k, home_adv, initial, scale)
    return ratings
