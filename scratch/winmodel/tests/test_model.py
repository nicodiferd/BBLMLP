"""LightGBM + isotonic calibration, judged on Brier and calibration."""

import numpy as np
import pandas as pd
import pytest

from winmodel.evaluate import walk_forward_evaluate
from winmodel.model import fit_calibrated_lgbm, predict_home_win_prob

INFORMATIVE = ["feat_strength_diff", "feat_noise_1", "feat_noise_2"]
NOISE_ONLY = ["feat_noise_1", "feat_noise_2"]


def _split_by_date(games: pd.DataFrame, frac: float = 0.7):
    cutoff = games["game_date"].quantile(frac)
    return games[games["game_date"] <= cutoff], games[games["game_date"] > cutoff]


@pytest.fixture(scope="module")
def fitted(large_games):
    train, test = _split_by_date(large_games)
    model = fit_calibrated_lgbm(train, INFORMATIVE)
    return model, train, test


def test_predictions_are_probabilities_aligned_to_input_index(fitted):
    model, _, test = fitted
    probs = predict_home_win_prob(model, test)
    assert isinstance(probs, pd.Series)
    assert probs.index.equals(test.index)
    assert ((probs >= 0.0) & (probs <= 1.0)).all()


def test_fit_and_predict_do_not_mutate_inputs(large_games):
    train, test = _split_by_date(large_games)
    train_before = train.copy(deep=True)
    test_before = test.copy(deep=True)
    model = fit_calibrated_lgbm(train, INFORMATIVE)
    predict_home_win_prob(model, test)
    pd.testing.assert_frame_equal(train, train_before)
    pd.testing.assert_frame_equal(test, test_before)


def test_feature_columns_are_swappable_and_informative_features_win(large_games):
    train, test = _split_by_date(large_games)
    y = test["home_win"].to_numpy()

    briers = {}
    for cols in (INFORMATIVE, NOISE_ONLY):
        model = fit_calibrated_lgbm(train, cols)
        p = predict_home_win_prob(model, test).to_numpy()
        briers[tuple(cols)] = np.mean((p - y) ** 2)

    assert briers[tuple(INFORMATIVE)] < briers[tuple(NOISE_ONLY)] - 0.01


def test_missing_feature_column_raises(fitted, large_games):
    model, _, test = fitted
    with pytest.raises(KeyError):
        predict_home_win_prob(model, test.drop(columns=["feat_strength_diff"]))
    with pytest.raises(KeyError):
        fit_calibrated_lgbm(large_games, ["feat_strength_diff", "no_such_feature"])


def test_calibration_slice_is_most_recent_data(fitted):
    model, train, _ = fitted
    frac_after_cutoff = (train["game_date"] >= model.calibration_cutoff).mean()
    assert 0.10 <= frac_after_cutoff <= 0.45  # ~calib_frac, in whole-day chunks
    assert model.calibration_cutoff > train["game_date"].quantile(0.5)


def test_calibrated_probs_are_monotone_in_raw_booster_scores(fitted):
    model, _, test = fitted
    raw = model.booster.predict_proba(test[list(model.feature_cols)])[:, 1]
    calibrated = predict_home_win_prob(model, test).to_numpy()
    order = np.argsort(raw)
    assert (np.diff(calibrated[order]) >= -1e-12).all()


def test_predictions_never_reach_certainty(fitted):
    """Isotonic ends must not emit 0/1: certainty from ~400 calibration rows
    is never justified and makes log-loss unbounded."""
    model, _, test = fitted
    probs = predict_home_win_prob(model, test)
    assert probs.min() >= 0.01
    assert probs.max() <= 0.99


def test_refuses_tiny_training_sets(large_games):
    with pytest.raises(ValueError):
        fit_calibrated_lgbm(large_games.head(8), INFORMATIVE)


def test_walk_forward_brier_beats_coin_flip(large_games):
    def predict(train_df, test_df):
        model = fit_calibrated_lgbm(train_df, INFORMATIVE)
        return predict_home_win_prob(model, test_df).to_numpy()

    result = walk_forward_evaluate(
        large_games, predict, n_splits=3, min_train_frac=0.4
    )
    assert result["brier"] < 0.24
    assert result["log_loss"] < np.log(2)


def test_walk_forward_predictions_are_well_calibrated(large_games):
    def predict(train_df, test_df):
        model = fit_calibrated_lgbm(train_df, INFORMATIVE)
        return predict_home_win_prob(model, test_df).to_numpy()

    result = walk_forward_evaluate(
        large_games, predict, n_splits=3, min_train_frac=0.4
    )
    table = result["reliability"]
    ece = float(
        ((table["mean_predicted"] - table["frac_positive"]).abs() * table["n"]).sum()
        / table["n"].sum()
    )
    assert ece < 0.07
