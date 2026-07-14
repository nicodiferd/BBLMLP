import pandas as pd
from bblmlp.ingest.mlb.rollups import pitcher_game_stats, lineup


def _pitches():
    # one game: SF (home) bats bottom, COL (away) bats top.
    # COL pitcher 900 starts (first pitch of the game, top of 1st? no—home pitches in top1)
    return pd.DataFrame({
        "game_pk": [1,1,1,1],
        "season": [2024]*4,
        "inning": [1,1,1,2],
        "inning_topbot": ["Top","Top","Bot","Bot"],
        "home_team": ["SF"]*4, "away_team": ["COL"]*4,
        "pitcher": [500,500,900,900],     # SF pitcher 500 throws in Top1; COL 900 in Bot1
        "batter":  [10,11,20,21],
        "at_bat_number": [1,2,3,4],
        "pitch_number": [1,1,1,1],
        "events": ["strikeout","walk","single","field_out"],
        "description": ["swinging_strike","ball","hit_into_play","hit_into_play"],
        "estimated_woba_using_speedangle": [0.0,0.0,0.9,0.1],
        "release_speed": [95,96,93,92],
    })

def test_starter_is_first_pitcher_for_each_side():
    out = pitcher_game_stats(_pitches())
    starters = set(out[out["is_starter"]]["pitcher"])
    assert starters == {500, 900}

def test_lineup_orders_batters_by_first_appearance():
    lo = lineup(_pitches())
    col = lo[lo["team"] == "COL"].sort_values("batting_order")
    assert list(col["batter"]) == [10, 11]  # COL bats in the Top half

def test_pitcher_game_stats_includes_fielding_team():
    out = pitcher_game_stats(_pitches())
    # pitcher 500 fields for SF (throws in Top1, i.e. the home/fielding side when away bats)
    # pitcher 900 fields for COL (throws in Bot1)
    row_500 = out[out["pitcher"] == 500].iloc[0]
    row_900 = out[out["pitcher"] == 900].iloc[0]
    assert row_500["team"] == "SF"
    assert row_900["team"] == "COL"
