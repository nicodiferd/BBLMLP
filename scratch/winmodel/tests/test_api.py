"""The package root re-exports the whole public surface."""


def test_public_api_is_importable_from_package_root():
    from winmodel import (  # noqa: F401
        elo_probabilities,
        final_elo_ratings,
        brier_score,
        log_loss_score,
        reliability_table,
        walk_forward_splits,
        evaluate_predictions,
        walk_forward_evaluate,
        CalibratedModel,
        fit_calibrated_lgbm,
        predict_home_win_prob,
    )
