"""Elo/Bradley-Terry baseline: pre-game P(home_win) from chronological updates."""

import numpy as np
import pandas as pd
import pytest

from winmodel.elo import elo_probabilities, final_elo_ratings


def _two_team_games(outcomes: list[int]) -> pd.DataFrame:
    start = pd.Timestamp("2024-04-01")
    return pd.DataFrame(
        {
            "game_pk": range(1, len(outcomes) + 1),
            "game_date": [start + pd.Timedelta(days=i) for i in range(len(outcomes))],
            "home_team": "A",
            "away_team": "B",
            "home_win": outcomes,
        }
    )


def test_first_game_is_even_money_without_home_advantage():
    games = _two_team_games([1])
    probs = elo_probabilities(games, home_adv=0.0)
    assert probs.iloc[0] == pytest.approx(0.5)


def test_home_advantage_raises_first_game_probability():
    games = _two_team_games([1])
    probs = elo_probabilities(games, home_adv=50.0)
    assert probs.iloc[0] > 0.5


def test_probabilities_stay_inside_unit_interval(small_games):
    probs = elo_probabilities(small_games)
    assert ((probs > 0.0) & (probs < 1.0)).all()


def test_repeated_winner_becomes_favourite():
    games = _two_team_games([1] * 10)
    probs = elo_probabilities(games, home_adv=0.0)
    assert probs.iloc[-1] > 0.6
    assert probs.is_monotonic_increasing


def test_updates_run_in_date_order_regardless_of_row_order(small_games):
    shuffled = small_games.sample(frac=1.0, random_state=3)
    probs_sorted = elo_probabilities(small_games)
    probs_shuffled = elo_probabilities(shuffled)
    aligned = probs_shuffled.reindex(small_games.index)
    pd.testing.assert_series_equal(probs_sorted, aligned)


def test_input_dataframe_is_not_mutated(small_games):
    before = small_games.copy(deep=True)
    elo_probabilities(small_games)
    final_elo_ratings(small_games)
    pd.testing.assert_frame_equal(small_games, before)


def test_result_aligns_with_input_index(small_games):
    reindexed = small_games.set_index(small_games.index * 10 + 3)
    probs = elo_probabilities(reindexed)
    assert probs.index.equals(reindexed.index)


def test_final_ratings_recover_true_strength_order(small_world):
    games, strengths = small_world
    ratings = final_elo_ratings(games)
    truth = pd.Series(strengths)
    est = pd.Series(ratings).reindex(truth.index)
    rank_corr = truth.rank().corr(est.rank())
    assert rank_corr > 0.7


def test_probabilities_are_calibrated_against_true_world(small_world):
    """Elo should beat a coin flip on Brier and track the generating probs."""
    games, _ = small_world
    probs = elo_probabilities(games)
    # Skip the burn-in where ratings are still near their initial value.
    settled = games.index[len(games) // 3 :]
    p = probs.loc[settled].to_numpy()
    y = games.loc[settled, "home_win"].to_numpy()
    true_p = games.loc[settled, "true_p"].to_numpy()

    brier = np.mean((p - y) ** 2)
    coin_flip_brier = np.mean((0.5 - y) ** 2)
    assert brier < coin_flip_brier - 0.01
    assert np.mean(np.abs(p - true_p)) < 0.10
