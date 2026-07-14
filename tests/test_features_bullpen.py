import duckdb
import pandas as pd
import pytest

from bblmlp.features.bullpen import bullpen_rolling_features


def _bullpen_game_stats():
    # One team (SF), 3 consecutive bullpen-games.
    return pd.DataFrame({
        "game_pk": [1, 2, 3],
        "season": [2024] * 3,
        "team": ["SF"] * 3,
        "pitches": [35, 40, 30],
        "batters_faced": [10, 11, 9],
        "k": [3, 4, 2],
        "bb": [1, 2, 1],
        "whiffs": [6, 7, 5],
        "n_pitchers": [2, 3, 2],
        "avg_velo": [94.3, 95.1, 93.8],
        "swstr_pct": [6 / 35, 7 / 40, 5 / 30],
    })


def _games():
    return pd.DataFrame({
        "game_pk": [1, 2, 3],
        "game_date": ["2024-03-15", "2024-03-16", "2024-03-17"],
        "game_datetime": ["2024-03-15T18:00", "2024-03-16T18:00", "2024-03-17T18:00"],
    })


def test_bullpen_first_game_has_no_history():
    con = duckdb.connect(":memory:")
    out = bullpen_rolling_features(con, _bullpen_game_stats(), _games())
    row = out[out["game_pk"] == 1].iloc[0]
    assert row["n_games_10"] == 0
    assert pd.isna(row["k_pct_10"])


def test_bullpen_direct_sum_over_sum_reconstruction():
    con = duckdb.connect(":memory:")
    out = bullpen_rolling_features(con, _bullpen_game_stats(), _games())
    row = out[out["game_pk"] == 3].iloc[0]
    # trailing window over games 1, 2
    expected_k_pct = (3 + 4) / (10 + 11)
    expected_swstr = (6 + 7) / (35 + 40)
    assert row["k_pct_10"] == pytest.approx(expected_k_pct)
    assert row["swstr_pct_10"] == pytest.approx(expected_swstr)
    assert row["n_games_10"] == 2


def test_bullpen_avg_velo_is_plain_trailing_mean():
    con = duckdb.connect(":memory:")
    out = bullpen_rolling_features(con, _bullpen_game_stats(), _games())
    row = out[out["game_pk"] == 3].iloc[0]
    assert row["avg_velo_10"] == pytest.approx((94.3 + 95.1) / 2)


def test_bullpen_leakage_perturbing_own_stats_does_not_change_own_row():
    con = duckdb.connect(":memory:")
    baseline = bullpen_rolling_features(con, _bullpen_game_stats(), _games())
    baseline_row3 = baseline[baseline["game_pk"] == 3].iloc[0]

    perturbed = _bullpen_game_stats()
    perturbed.loc[perturbed["game_pk"] == 3, "k"] = 99
    con2 = duckdb.connect(":memory:")
    out = bullpen_rolling_features(con2, perturbed, _games())
    row3 = out[out["game_pk"] == 3].iloc[0]
    assert row3["k_pct_10"] == pytest.approx(baseline_row3["k_pct_10"])


def test_bullpen_doubleheader_games_ordered_by_datetime_not_just_date():
    # pk 20 is the nightcap (19:00), pk 21 is the opener (13:00) -- deliberately
    # inverted game_pk order so a game_datetime-dropping regression would fail this.
    bullpen_game_stats = pd.DataFrame({
        "game_pk": [21, 20],
        "season": [2024] * 2,
        "team": ["SF"] * 2,
        "pitches": [35, 40],
        "batters_faced": [10, 11],
        "k": [3, 4],
        "bb": [1, 2],
        "whiffs": [6, 7],
        "n_pitchers": [2, 3],
        "avg_velo": [94.3, 95.1],
        "swstr_pct": [6 / 35, 7 / 40],
    })
    games = pd.DataFrame({
        "game_pk": [21, 20],
        "game_date": ["2024-05-01", "2024-05-01"],
        "game_datetime": ["2024-05-01T13:00", "2024-05-01T19:00"],
    })
    con = duckdb.connect(":memory:")
    out = bullpen_rolling_features(con, bullpen_game_stats, games)

    row_nightcap = out[out["game_pk"] == 20].iloc[0]
    assert row_nightcap["n_games_10"] == 1
    assert row_nightcap["k_pct_10"] == pytest.approx(3 / 10)  # sees only pk 21 (the opener)

    row_opener = out[out["game_pk"] == 21].iloc[0]
    assert row_opener["n_games_10"] == 0
