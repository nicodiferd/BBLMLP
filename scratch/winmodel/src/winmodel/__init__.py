"""Standalone MLB game-winner model library.

Pure functions over pandas DataFrames. Expected input columns:
game_pk, game_date, home_team, away_team, home_win, plus feature columns.
"""

from winmodel.elo import elo_probabilities, final_elo_ratings
from winmodel.evaluate import (
    brier_score,
    evaluate_predictions,
    log_loss_score,
    reliability_table,
    walk_forward_evaluate,
    walk_forward_splits,
)
from winmodel.model import (
    CalibratedModel,
    fit_calibrated_lgbm,
    predict_home_win_prob,
)

__all__ = [
    "elo_probabilities",
    "final_elo_ratings",
    "brier_score",
    "log_loss_score",
    "reliability_table",
    "walk_forward_splits",
    "evaluate_predictions",
    "walk_forward_evaluate",
    "CalibratedModel",
    "fit_calibrated_lgbm",
    "predict_home_win_prob",
]
