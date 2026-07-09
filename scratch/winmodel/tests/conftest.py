"""Shared synthetic-data fixtures.

Games are generated from a latent Bradley-Terry world: each team has a fixed
log-odds strength, the home side gets a constant additive edge, and outcomes
are Bernoulli draws from the resulting probability. `true_p` and the returned
strengths exist only so tests can measure calibration against ground truth —
they are never model inputs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

HOME_ADV_LOGIT = 0.25


def make_synthetic_games(
    n_teams: int = 8,
    n_days: int = 60,
    games_per_day: int = 6,
    seed: int = 7,
    home_adv: float = HOME_ADV_LOGIT,
) -> tuple[pd.DataFrame, dict[str, float]]:
    rng = np.random.default_rng(seed)
    teams = [f"T{i}" for i in range(n_teams)]
    strengths = dict(zip(teams, rng.normal(0.0, 0.6, n_teams)))

    start = pd.Timestamp("2024-04-01")
    rows = []
    game_pk = 100_000
    for day in range(n_days):
        for _ in range(games_per_day):
            hi, ai = rng.choice(n_teams, size=2, replace=False)
            home, away = teams[hi], teams[ai]
            logit = strengths[home] - strengths[away] + home_adv
            p = 1.0 / (1.0 + np.exp(-logit))
            rows.append(
                {
                    "game_pk": game_pk,
                    "game_date": start + pd.Timedelta(days=day),
                    "home_team": home,
                    "away_team": away,
                    "home_win": int(rng.random() < p),
                    "true_p": p,
                    # Placeholder features: one informative (noisy strength
                    # gap), two pure noise. Real features slot in later by
                    # passing different feature_cols.
                    "feat_strength_diff": strengths[home]
                    - strengths[away]
                    + rng.normal(0.0, 0.3),
                    "feat_noise_1": rng.normal(),
                    "feat_noise_2": rng.normal(),
                }
            )
            game_pk += 1
    return pd.DataFrame(rows), strengths


@pytest.fixture(scope="session")
def small_world() -> tuple[pd.DataFrame, dict[str, float]]:
    """~360 games: enough for Elo/metric tests, fast."""
    return make_synthetic_games(n_teams=8, n_days=60, games_per_day=6, seed=7)


@pytest.fixture(scope="session")
def small_games(small_world) -> pd.DataFrame:
    return small_world[0]


@pytest.fixture(scope="session")
def large_world() -> tuple[pd.DataFrame, dict[str, float]]:
    """~2160 games: enough signal for LightGBM + isotonic tests."""
    return make_synthetic_games(n_teams=12, n_days=180, games_per_day=12, seed=11)


@pytest.fixture(scope="session")
def large_games(large_world) -> pd.DataFrame:
    return large_world[0]
