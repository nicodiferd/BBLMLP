import duckdb
import pandas as pd
import pytest

from bblmlp.features.rolling import team_rolling_features, pitcher_rolling_features


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


def _pitcher_game_stats():
    # One pitcher (id 500), 3 starts.
    return pd.DataFrame({
        "game_pk": [1, 2, 3],
        "season": [2024] * 3,
        "pitcher": [500, 500, 500],
        "is_starter": [True, True, True],
        "pitches": [90, 95, 88],
        "batters_faced": [24, 26, 23],
        "avg_velo": [94.0, 93.5, 94.2],
        "k": [6, 7, 5],
        "bb": [2, 1, 3],
        "whiffs": [10, 12, 9],
    })


def _pitcher_games():
    return pd.DataFrame({
        "game_pk": [1, 2, 3],
        "game_date": ["2024-03-15", "2024-03-20", "2024-03-25"],
        "game_datetime": ["2024-03-15T18:00", "2024-03-20T18:00", "2024-03-25T18:00"],
    })


def test_pitcher_first_start_has_no_history():
    con = duckdb.connect(":memory:")
    out = pitcher_rolling_features(con, _pitcher_game_stats(), _pitcher_games())
    row = out[out["game_pk"] == 1].iloc[0]
    assert row["n_games_10"] == 0
    assert pd.isna(row["k_pct_10"])


def test_pitcher_direct_sum_over_sum_reconstruction():
    con = duckdb.connect(":memory:")
    out = pitcher_rolling_features(con, _pitcher_game_stats(), _pitcher_games())
    row = out[out["game_pk"] == 3].iloc[0]
    # trailing window over starts 1,2
    expected_k_pct = (6 + 7) / (24 + 26)
    expected_swstr = (10 + 12) / (90 + 95)
    assert row["k_pct_10"] == pytest.approx(expected_k_pct)
    assert row["swstr_pct_10"] == pytest.approx(expected_swstr)
    assert row["n_games_10"] == 2


def test_pitcher_avg_velo_is_plain_trailing_mean():
    con = duckdb.connect(":memory:")
    out = pitcher_rolling_features(con, _pitcher_game_stats(), _pitcher_games())
    row = out[out["game_pk"] == 3].iloc[0]
    assert row["avg_velo_10"] == pytest.approx((94.0 + 93.5) / 2)


def test_pitcher_is_starter_passes_through_unwindowed():
    con = duckdb.connect(":memory:")
    out = pitcher_rolling_features(con, _pitcher_game_stats(), _pitcher_games())
    assert out["is_starter"].tolist() == [True, True, True]


def test_pitcher_leakage_perturbing_own_stats_does_not_change_own_row():
    con = duckdb.connect(":memory:")
    baseline = pitcher_rolling_features(con, _pitcher_game_stats(), _pitcher_games())
    baseline_row3 = baseline[baseline["game_pk"] == 3].iloc[0]

    perturbed = _pitcher_game_stats()
    perturbed.loc[perturbed["game_pk"] == 3, "k"] = 99
    con2 = duckdb.connect(":memory:")
    out = pitcher_rolling_features(con2, perturbed, _pitcher_games())
    row3 = out[out["game_pk"] == 3].iloc[0]
    assert row3["k_pct_10"] == pytest.approx(baseline_row3["k_pct_10"])


def test_team_doubleheader_games_ordered_by_datetime_not_just_date():
    # Two games on the SAME game_date (a doubleheader) -- the earlier
    # game_datetime must be treated as happening first.
    team_game_stats = pd.DataFrame({
        "game_pk": [10, 11, 12],
        "season": [2024] * 3,
        "team": ["NYY"] * 3,
        "pa": [36, 34, 38],
        "xwoba": [0.30, 0.35, 0.28],
        "k_pct": [0.20, 0.30, 0.25],
        "bb_pct": [0.05, 0.06, 0.07],
    })
    games = pd.DataFrame({
        "game_pk": [10, 11, 12],
        "game_date": ["2024-05-01", "2024-05-01", "2024-05-02"],  # 10, 11 = doubleheader
        "game_datetime": ["2024-05-01T13:00", "2024-05-01T19:00", "2024-05-02T18:00"],
    })
    con = duckdb.connect(":memory:")
    out = team_rolling_features(con, team_game_stats, games)

    row_g2 = out[out["game_pk"] == 11].iloc[0]  # game 2 of the doubleheader
    assert row_g2["n_games_30"] == 1
    assert row_g2["k_pct_30"] == pytest.approx(0.20)  # sees only game 10 (the day's opener)

    row_next_day = out[out["game_pk"] == 12].iloc[0]
    assert row_next_day["n_games_30"] == 2  # sees both games 10 and 11


def test_pitcher_doubleheader_starts_ordered_by_datetime_not_just_date():
    pitcher_game_stats = pd.DataFrame({
        "game_pk": [20, 21],
        "season": [2024] * 2,
        "pitcher": [700, 700],
        "is_starter": [True, True],
        "pitches": [90, 85],
        "batters_faced": [24, 22],
        "avg_velo": [93.0, 92.0],
        "k": [5, 6],
        "bb": [2, 1],
        "whiffs": [8, 9],
    })
    games = pd.DataFrame({
        "game_pk": [20, 21],
        "game_date": ["2024-05-01", "2024-05-01"],
        "game_datetime": ["2024-05-01T13:00", "2024-05-01T19:00"],
    })
    con = duckdb.connect(":memory:")
    out = pitcher_rolling_features(con, pitcher_game_stats, games)
    row_g2 = out[out["game_pk"] == 21].iloc[0]
    assert row_g2["n_games_10"] == 1
    assert row_g2["k_pct_10"] == pytest.approx(5 / 24)
