"""Evaluation harness: probability metrics + strict walk-forward splitting."""

import inspect

import numpy as np
import pandas as pd
import pytest

from winmodel.evaluate import (
    brier_score,
    log_loss_score,
    reliability_table,
    walk_forward_splits,
    evaluate_predictions,
    walk_forward_evaluate,
)


# --- metrics -----------------------------------------------------------------


def test_brier_score_known_values():
    y = np.array([1, 0, 1, 0])
    assert brier_score(y, np.array([1.0, 0.0, 1.0, 0.0])) == pytest.approx(0.0)
    assert brier_score(y, np.array([0.0, 1.0, 0.0, 1.0])) == pytest.approx(1.0)
    assert brier_score(y, np.full(4, 0.5)) == pytest.approx(0.25)


def test_log_loss_known_values():
    y = np.array([1, 0])
    assert log_loss_score(y, np.array([0.5, 0.5])) == pytest.approx(np.log(2))
    assert log_loss_score(y, np.array([0.9, 0.1])) == pytest.approx(-np.log(0.9))


def test_log_loss_is_finite_at_hard_zero_and_one():
    y = np.array([1, 0])
    loss = log_loss_score(y, np.array([0.0, 1.0]))
    assert np.isfinite(loss)
    assert loss > 10  # confidently wrong must still be punished hard


def test_metrics_accept_pandas_series(small_games):
    p = pd.Series(0.5, index=small_games.index)
    assert brier_score(small_games["home_win"], p) == pytest.approx(0.25)


# --- reliability table --------------------------------------------------------


def test_reliability_table_bins_and_counts():
    p = np.array([0.05, 0.15, 0.15, 0.85, 0.95, 0.95])
    y = np.array([0, 0, 1, 1, 1, 1])
    table = reliability_table(y, p, n_bins=10)

    assert list(table.columns) == [
        "bin_left",
        "bin_right",
        "n",
        "mean_predicted",
        "frac_positive",
    ]
    assert table["n"].sum() == len(y)
    # Empty bins are dropped: only bins around 0.0-0.2 and 0.8-1.0 are present.
    assert (table["n"] > 0).all()

    first = table.iloc[0]
    assert first["n"] == 1
    assert first["mean_predicted"] == pytest.approx(0.05)
    assert first["frac_positive"] == pytest.approx(0.0)


def test_reliability_table_recovers_perfect_calibration():
    rng = np.random.default_rng(0)
    p = rng.uniform(0.05, 0.95, 20_000)
    y = (rng.random(20_000) < p).astype(int)
    table = reliability_table(y, p, n_bins=10)
    gaps = (table["mean_predicted"] - table["frac_positive"]).abs()
    assert gaps.max() < 0.03


# --- walk-forward splits -------------------------------------------------------


def test_walk_forward_train_always_strictly_precedes_test(small_games):
    splits = walk_forward_splits(small_games, n_splits=4)
    assert len(splits) == 4
    for train_idx, test_idx in splits:
        train_dates = small_games.loc[train_idx, "game_date"]
        test_dates = small_games.loc[test_idx, "game_date"]
        assert len(train_dates) > 0 and len(test_dates) > 0
        assert train_dates.max() < test_dates.min()


def test_walk_forward_same_date_never_straddles_train_and_test(small_games):
    for train_idx, test_idx in walk_forward_splits(small_games, n_splits=4):
        overlap = set(small_games.loc[train_idx, "game_date"]) & set(
            small_games.loc[test_idx, "game_date"]
        )
        assert overlap == set()


def test_walk_forward_test_sets_are_disjoint_and_expanding_train(small_games):
    splits = walk_forward_splits(small_games, n_splits=4)
    seen: set = set()
    prev_train: set = set()
    for train_idx, test_idx in splits:
        test_set = set(test_idx)
        assert seen.isdisjoint(test_set)
        seen |= test_set
        train_set = set(train_idx)
        assert prev_train <= train_set
        prev_train = train_set


def test_walk_forward_is_row_order_invariant(small_games):
    shuffled = small_games.sample(frac=1.0, random_state=5)
    by_pk = lambda df, splits: [
        (set(df.loc[tr, "game_pk"]), set(df.loc[te, "game_pk"])) for tr, te in splits
    ]
    assert by_pk(small_games, walk_forward_splits(small_games, n_splits=3)) == by_pk(
        shuffled, walk_forward_splits(shuffled, n_splits=3)
    )


def test_walk_forward_offers_no_shuffle_knob():
    """The API must make a random split impossible, not merely non-default."""
    params = inspect.signature(walk_forward_splits).parameters
    forbidden = {"shuffle", "random_state", "seed"}
    assert forbidden.isdisjoint(params)


def test_walk_forward_rejects_too_few_dates():
    df = pd.DataFrame(
        {
            "game_pk": [1, 2],
            "game_date": pd.to_datetime(["2024-04-01", "2024-04-02"]),
            "home_team": ["A", "A"],
            "away_team": ["B", "B"],
            "home_win": [1, 0],
        }
    )
    with pytest.raises(ValueError):
        walk_forward_splits(df, n_splits=5)


# --- end-to-end harness ---------------------------------------------------------


def test_evaluate_predictions_bundle(small_games):
    p = pd.Series(0.5, index=small_games.index)
    result = evaluate_predictions(small_games["home_win"], p, n_bins=10)
    assert result["n"] == len(small_games)
    assert result["brier"] == pytest.approx(0.25)
    assert result["log_loss"] == pytest.approx(np.log(2))
    assert isinstance(result["reliability"], pd.DataFrame)


def test_walk_forward_evaluate_scores_out_of_sample_only(small_games):
    calls = []

    def constant_half(train_df, test_df):
        calls.append((train_df, test_df))
        return np.full(len(test_df), 0.5)

    result = walk_forward_evaluate(small_games, constant_half, n_splits=4)

    assert result["brier"] == pytest.approx(0.25)
    assert 0 < result["n"] < len(small_games)  # warmup window is never scored
    assert len(result["predictions"]) == result["n"]

    # The harness must only ever hand the model past data to train on.
    for train_df, test_df in calls:
        assert train_df["game_date"].max() < test_df["game_date"].min()


def test_walk_forward_evaluate_beats_coin_flip_with_true_probs(small_games):
    def oracle(train_df, test_df):
        return test_df["true_p"].to_numpy()

    result = walk_forward_evaluate(small_games, oracle, n_splits=4)
    assert result["brier"] < 0.25
    assert result["log_loss"] < np.log(2)
