"""Scoring and strictly time-ordered evaluation for win probabilities.

The walk-forward splitter is the only splitter here on purpose: every split
puts all training dates strictly before all test dates, whole dates never
straddle the boundary, and there is deliberately no shuffle/random knob.
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np
import pandas as pd

_EPS = 1e-15


def brier_score(y_true, p) -> float:
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(p, dtype=float)
    return float(np.mean((p - y) ** 2))


def log_loss_score(y_true, p, *, eps: float = _EPS) -> float:
    y = np.asarray(y_true, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), eps, 1.0 - eps)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def reliability_table(y_true, p, *, n_bins: int = 10) -> pd.DataFrame:
    """Per-bin mean predicted probability vs. observed win rate.

    Bins are equal-width over [0, 1]; empty bins are dropped.
    """
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(p, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.clip(np.digitize(p, edges) - 1, 0, n_bins - 1)

    rows = []
    for b in np.unique(bin_idx):
        mask = bin_idx == b
        rows.append(
            {
                "bin_left": edges[b],
                "bin_right": edges[b + 1],
                "n": int(mask.sum()),
                "mean_predicted": float(p[mask].mean()),
                "frac_positive": float(y[mask].mean()),
            }
        )
    return pd.DataFrame(
        rows, columns=["bin_left", "bin_right", "n", "mean_predicted", "frac_positive"]
    )


def walk_forward_splits(
    games: pd.DataFrame,
    *,
    n_splits: int = 5,
    min_train_frac: float = 0.3,
    date_col: str = "game_date",
) -> list[tuple[pd.Index, pd.Index]]:
    """Expanding-window splits over whole dates, oldest to newest.

    The first `min_train_frac` of unique dates form the initial training
    window and are never scored. The remaining dates are cut into `n_splits`
    contiguous, chronological test chunks; each chunk trains on everything
    that came before it.
    """
    dates = np.sort(games[date_col].unique())
    n_warmup = max(1, math.ceil(min_train_frac * len(dates)))
    test_dates = dates[n_warmup:]
    if len(test_dates) < n_splits:
        raise ValueError(
            f"Need at least {n_splits} unique dates after the warmup window, "
            f"got {len(test_dates)}."
        )

    splits: list[tuple[pd.Index, pd.Index]] = []
    for chunk in np.array_split(test_dates, n_splits):
        train_idx = games.index[games[date_col] < chunk[0]]
        test_idx = games.index[games[date_col].isin(chunk)]
        assert games.loc[train_idx, date_col].max() < games.loc[test_idx, date_col].min()
        splits.append((train_idx, test_idx))
    return splits


def evaluate_predictions(y_true, p, *, n_bins: int = 10) -> dict:
    y = np.asarray(y_true, dtype=float)
    return {
        "n": len(y),
        "brier": brier_score(y, p),
        "log_loss": log_loss_score(y, p),
        "reliability": reliability_table(y, p, n_bins=n_bins),
    }


def walk_forward_evaluate(
    games: pd.DataFrame,
    predict_fn: Callable[[pd.DataFrame, pd.DataFrame], np.ndarray],
    *,
    n_splits: int = 5,
    min_train_frac: float = 0.3,
    label_col: str = "home_win",
    date_col: str = "game_date",
    n_bins: int = 10,
) -> dict:
    """Score `predict_fn` on pooled out-of-sample walk-forward predictions.

    `predict_fn(train_df, test_df)` must return P(home_win) for each test row;
    it only ever sees training rows dated strictly before its test rows.
    """
    splits = walk_forward_splits(
        games, n_splits=n_splits, min_train_frac=min_train_frac, date_col=date_col
    )
    fold_preds = []
    for train_idx, test_idx in splits:
        p = predict_fn(games.loc[train_idx], games.loc[test_idx])
        fold_preds.append(pd.Series(np.asarray(p, dtype=float), index=test_idx))

    predictions = pd.concat(fold_preds)
    result = evaluate_predictions(
        games.loc[predictions.index, label_col], predictions, n_bins=n_bins
    )
    result["predictions"] = predictions
    return result
