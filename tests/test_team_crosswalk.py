import pandas as pd
import pytest

from bblmlp.ingest.mlb.team_crosswalk import build_team_crosswalk


def _standings(rows):
    return pd.DataFrame(rows, columns=["season", "team_id", "team_name"])


def _games(rows):
    return pd.DataFrame(rows, columns=["game_pk", "season", "game_type", "home_team_id", "away_team_id"])


def _statcast(rows):
    return pd.DataFrame(rows, columns=["game_pk", "home_team", "away_team"])


def _fangraphs(rows):
    return pd.DataFrame(rows, columns=["season", "team"])


def test_derives_statcast_abbr_from_game_pk_join():
    standings = _standings([(2024, 137, "San Francisco Giants"), (2024, 115, "Colorado Rockies")])
    games = _games([(1, 2024, "R", 137, 115)])
    statcast = _statcast([(1, "SF", "COL")])
    fangraphs = _fangraphs([(2024, "SFG"), (2024, "COL")])

    out = build_team_crosswalk(standings, games, statcast, fangraphs)

    row = out[out["team_id"] == 137].iloc[0]
    assert row["statcast_abbr"] == "SF"
    assert row["fangraphs_abbr"] == "SFG"
    assert row["team_name"] == "San Francisco Giants"


def test_ignores_non_regular_season_games_for_statcast_abbr():
    standings = _standings([(2024, 137, "San Francisco Giants"), (2024, 115, "Colorado Rockies")])
    games = _games([
        (1, 2024, "R", 137, 115),
        # exhibition game vs. a non-MLB opponent with an unrelated team_id — must not pollute SF's mode
        (2, 2024, "E", 137, 9999),
    ])
    statcast = _statcast([(1, "SF", "COL"), (2, "SF", "TOKYO")])
    fangraphs = _fangraphs([(2024, "SFG"), (2024, "COL")])

    out = build_team_crosswalk(standings, games, statcast, fangraphs)

    row = out[out["team_id"] == 137].iloc[0]
    assert row["statcast_abbr"] == "SF"


def test_applies_season_scoped_fangraphs_override():
    # Athletics: team_id 133 is "OAK" through 2024, "ATH" from 2025 on (Sacramento relocation).
    standings = _standings([(2024, 133, "Oakland Athletics"), (2025, 133, "Athletics")])
    games = _games([(1, 2024, "R", 133, 137), (2, 2025, "R", 133, 137)])
    statcast = _statcast([(1, "ATH", "SF"), (2, "ATH", "SF")])
    fangraphs = _fangraphs([(2024, "OAK"), (2025, "ATH")])

    out = build_team_crosswalk(standings, games, statcast, fangraphs)

    assert out[(out["team_id"] == 133) & (out["season"] == 2024)].iloc[0]["fangraphs_abbr"] == "OAK"
    assert out[(out["team_id"] == 133) & (out["season"] == 2025)].iloc[0]["fangraphs_abbr"] == "ATH"


def test_raises_when_expected_fangraphs_abbr_is_not_in_ingested_data():
    # Simulates undetected drift: our static map still says "TBR" for the Rays
    # (no override added yet), but the real ingested FanGraphs rows for this
    # season only have "TB2" — must fail loudly, not silently mis-join.
    standings = _standings([(2030, 139, "Tampa Bay Rays")])
    games = _games([(1, 2030, "R", 139, 137)])
    statcast = _statcast([(1, "TB", "SF")])
    fangraphs = _fangraphs([(2030, "TB2")])

    with pytest.raises(ValueError, match="139"):
        build_team_crosswalk(standings, games, statcast, fangraphs)


def test_skips_fangraphs_validation_for_seasons_not_yet_ingested():
    # FanGraphs data for 2026 hasn't been ingested at all yet — should not raise,
    # and fangraphs_abbr should just be the static default.
    standings = _standings([(2026, 137, "San Francisco Giants")])
    games = _games([(1, 2026, "R", 137, 115)])
    statcast = _statcast([(1, "SF", "COL")])
    fangraphs = _fangraphs([])

    out = build_team_crosswalk(standings, games, statcast, fangraphs)
    assert out.iloc[0]["fangraphs_abbr"] == "SFG"


def test_all_30_teams_have_no_missing_fangraphs_mapping():
    from bblmlp.ingest.mlb.team_crosswalk import FANGRAPHS_ABBR_BY_TEAM_ID
    assert len(FANGRAPHS_ABBR_BY_TEAM_ID) == 30
    assert len(set(FANGRAPHS_ABBR_BY_TEAM_ID.values())) == 30
