"""LightGBM game-winner classifier wrapped in isotonic calibration.

The training window is split by time: the model fits on the earlier slice and
the isotonic calibrator fits on the most recent held-out slice, so calibration
is judged on data the booster never saw. Feature columns are passed in by the
caller, so real features slot in without touching this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.isotonic import IsotonicRegression

MIN_TRAIN_ROWS = 50

# Tuned on walk-forward Brier over the synthetic fixture: shallow stumps
# generalize far better than deeper trees at a few thousand rows and a small
# feature set. Override any of these via `lgbm_params` as features grow.
DEFAULT_LGBM_PARAMS: dict = {
    "n_estimators": 200,
    "learning_rate": 0.05,
    "num_leaves": 3,
    "max_depth": 2,
    "min_child_samples": 50,
    "random_state": 0,
    "n_jobs": 1,
    "verbosity": -1,
}


@dataclass(frozen=True)
class CalibratedModel:
    booster: LGBMClassifier
    calibrator: IsotonicRegression
    feature_cols: tuple[str, ...]
    calibration_cutoff: pd.Timestamp


def _require_columns(df: pd.DataFrame, cols: list[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KeyError(f"Missing feature columns: {missing}")


def fit_calibrated_lgbm(
    train: pd.DataFrame,
    feature_cols,
    *,
    label_col: str = "home_win",
    date_col: str = "game_date",
    calib_frac: float = 0.25,
    prob_clip: float = 0.02,
    lgbm_params: dict | None = None,
) -> CalibratedModel:
    features = list(feature_cols)
    _require_columns(train, features)
    if len(train) < MIN_TRAIN_ROWS:
        raise ValueError(
            f"Need at least {MIN_TRAIN_ROWS} training rows, got {len(train)}."
        )

    ordered = train.sort_values([date_col, "game_pk"], kind="stable")
    n_calib = max(1, math.ceil(calib_frac * len(ordered)))
    fit_slice = ordered.iloc[:-n_calib]
    calib_slice = ordered.iloc[-n_calib:]

    params = {**DEFAULT_LGBM_PARAMS, **(lgbm_params or {})}
    booster = LGBMClassifier(**params)
    booster.fit(fit_slice[features], fit_slice[label_col])

    raw = booster.predict_proba(calib_slice[features])[:, 1]
    # Keep the isotonic ends away from 0/1: a finite calibration slice never
    # justifies certainty, and one wrong 0/1 makes log-loss unbounded.
    calibrator = IsotonicRegression(
        y_min=prob_clip, y_max=1.0 - prob_clip, out_of_bounds="clip"
    )
    calibrator.fit(raw, calib_slice[label_col])

    return CalibratedModel(
        booster=booster,
        calibrator=calibrator,
        feature_cols=tuple(features),
        calibration_cutoff=calib_slice[date_col].min(),
    )


def predict_home_win_prob(model: CalibratedModel, games: pd.DataFrame) -> pd.Series:
    features = list(model.feature_cols)
    _require_columns(games, features)
    raw = model.booster.predict_proba(games[features])[:, 1]
    return pd.Series(model.calibrator.predict(raw), index=games.index, name="p_home")
