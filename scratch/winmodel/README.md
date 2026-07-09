# winmodel

Standalone MLB game-winner model library: pure functions over pandas
DataFrames, no CLI, no data ingestion, no database. Built to be graduated into
`bblmlp` later — nothing here imports from or writes to the main project.

Expected input columns: `game_pk`, `game_date`, `home_team`, `away_team`,
`home_win`, plus whatever feature columns you pass explicitly. Feature columns
are always caller-supplied (`feature_cols`), so real features slot in without
touching library code.

## Pieces

- `winmodel.elo` — Elo/Bradley-Terry baseline. `elo_probabilities(games)`
  returns pre-game P(home_win) per row, updating ratings in strict
  `(game_date, game_pk)` order regardless of input row order.
- `winmodel.evaluate` — Brier score, log-loss, reliability-curve table, and a
  strict walk-forward splitter/harness. Every split puts all training dates
  strictly before all test dates; whole dates never straddle the boundary;
  there is deliberately no shuffle/random knob (a test enforces the API can't
  grow one).
- `winmodel.model` — LightGBM classifier wrapped in isotonic calibration. The
  training window is split by time: booster fits on the earlier slice,
  isotonic fits on the most recent held-out slice. Isotonic output is clipped
  away from 0/1 (`prob_clip`) so log-loss stays bounded.

## Usage

```python
from winmodel import (
    elo_probabilities, fit_calibrated_lgbm, predict_home_win_prob,
    walk_forward_evaluate,
)

FEATURES = ["feat_a", "feat_b"]          # swap in real features here

def lgbm_fn(train_df, test_df):
    model = fit_calibrated_lgbm(train_df, FEATURES)
    return predict_home_win_prob(model, test_df).to_numpy()

result = walk_forward_evaluate(games, lgbm_fn, n_splits=5)
result["brier"], result["log_loss"], result["reliability"]  # + "predictions"
```

Any `predict_fn(train_df, test_df) -> probs` plugs into the same harness, so
Elo and LightGBM are scored identically. On the synthetic Bradley-Terry
fixture (walk-forward, 1296 scored games): oracle Brier 0.2160, Elo 0.2227,
LightGBM+isotonic 0.2333, coin flip 0.2500. Elo wins there because the fixture
literally is a Bradley-Terry world; with real features the ordering should
flip.

## Tests

```bash
uv run --no-sync pytest
```

`--no-sync` matters on this machine: something (iCloud Desktop sync or uv
cache cloning) keeps re-setting the macOS `hidden` flag on the venv's `.pth`
files, and CPython ≥3.11 silently skips hidden `.pth` files, which breaks the
editable install that `uv run`'s pre-sync rewrites. Tests also add `src` to
`sys.path` via pytest's `pythonpath`, so they run either way.

Default LightGBM params are stumps (`num_leaves=3, max_depth=2`), tuned on
walk-forward Brier over the synthetic fixture — deeper trees overfit at a few
thousand rows and a handful of features. Override via `lgbm_params` as the
feature set grows.
