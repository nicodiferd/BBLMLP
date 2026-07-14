import duckdb
import pandas as pd
import pytest

from bblmlp.features.rolling import team_rolling_features


def _team_game_stats():
    # One team (NYY), 4 consecutive games, 2-day gap before game 3 to prove
    # the window is games-based, not calendar-based.
    return pd.DataFrame({
        "game_pk": [1, 2, 3, 4],
        "season": [2024] * 4,
        "team": ["NYY"] * 4,
        "pa": [36, 41, 42, 35],
        "xwoba": [0.30, 0.25, 0.40, 0.20],
        "k_pct": [0.250000, 0.170732, 0.261905, 0.142857],
        "bb_pct": [0.055556, 0.024390, 0.142857, 0.085714],
    })


def _games():
    return pd.DataFrame({
        "game_pk": [1, 2, 3, 4],
        "game_date": ["2024-03-15", "2024-03-16", "2024-03-19", "2024-03-20"],
        "game_datetime": [
            "2024-03-15T18:00", "2024-03-16T18:00", "2024-03-19T18:00", "2024-03-20T18:00",
        ],
    })


def test_first_game_has_no_history():
    con = duckdb.connect(":memory:")
    out = team_rolling_features(con, _team_game_stats(), _games())
    row = out[out["game_pk"] == 1].iloc[0]
    assert row["n_games_30"] == 0
    assert pd.isna(row["k_pct_30"])


def test_second_game_trailing_equals_first_games_own_rate():
    con = duckdb.connect(":memory:")
    out = team_rolling_features(con, _team_game_stats(), _games())
    row = out[out["game_pk"] == 2].iloc[0]
    assert row["n_games_30"] == 1
    assert row["k_pct_30"] == pytest.approx(0.250000)
    assert row["bb_pct_30"] == pytest.approx(0.055556)


def test_rate_reconstruction_is_pa_weighted_sum_not_mean_of_rates():
    con = duckdb.connect(":memory:")
    out = team_rolling_features(con, _team_game_stats(), _games())
    row = out[out["game_pk"] == 3].iloc[0]
    # trailing window over games 1,2 (30 PRECEDING covers everything before game 3)
    expected_k_pct = (0.250000 * 36 + 0.170732 * 41) / (36 + 41)
    expected_xwoba = (0.30 * 36 + 0.25 * 41) / (36 + 41)
    assert row["k_pct_30"] == pytest.approx(expected_k_pct)
    assert row["xwoba_30"] == pytest.approx(expected_xwoba)
    assert row["n_games_30"] == 2


def test_leakage_perturbing_a_games_own_stats_does_not_change_its_own_row():
    con = duckdb.connect(":memory:")
    baseline = team_rolling_features(con, _team_game_stats(), _games())
    baseline_row3 = baseline[baseline["game_pk"] == 3].iloc[0]

    perturbed = _team_game_stats()
    perturbed.loc[perturbed["game_pk"] == 3, "k_pct"] = 0.999  # blow up game 3's own value
    con2 = duckdb.connect(":memory:")
    out = team_rolling_features(con2, perturbed, _games())
    row3 = out[out["game_pk"] == 3].iloc[0]

    # game 3's own trailing feature must be unaffected by game 3's own perturbed value
    assert row3["k_pct_30"] == pytest.approx(baseline_row3["k_pct_30"])
    # but game 4's trailing feature, which looks back at game 3, must move
    row4 = out[out["game_pk"] == 4].iloc[0]
    baseline_row4 = baseline[baseline["game_pk"] == 4].iloc[0]
    assert row4["k_pct_30"] != pytest.approx(baseline_row4["k_pct_30"])


def test_gap_in_calendar_days_does_not_shrink_the_games_based_window():
    # games 2 -> 3 have a 3-calendar-day gap; window is still "games", not "days"
    con = duckdb.connect(":memory:")
    out = team_rolling_features(con, _team_game_stats(), _games())
    row = out[out["game_pk"] == 3].iloc[0]
    assert row["n_games_30"] == 2  # both prior games count, gap or not
