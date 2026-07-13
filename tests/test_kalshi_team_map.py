from bblmlp.ingest.kalshi.team_map import KALSHI_TEAM_CODES
from bblmlp.ingest.mlb.team_crosswalk import FANGRAPHS_ABBR_BY_TEAM_ID


def test_every_kalshi_code_maps_to_a_known_team_id():
    # Validated against the real, stable universe of 30 franchise ids (team_crosswalk's
    # own source of truth) so a future relocation/expansion would fail loudly here
    # instead of silently mis-joining Kalshi prices to the wrong game.
    assert set(KALSHI_TEAM_CODES.values()) == set(FANGRAPHS_ABBR_BY_TEAM_ID.keys())


def test_kalshi_codes_are_unique():
    assert len(KALSHI_TEAM_CODES) == 30
    assert len(set(KALSHI_TEAM_CODES.values())) == 30


def test_known_codes_spot_check():
    # Spot-check codes that don't obviously match MLB's own abbreviations
    # (confirmed live against Kalshi's API during design, 2026-07-12).
    assert KALSHI_TEAM_CODES["ATH"] == 133  # Athletics ("A's")
    assert KALSHI_TEAM_CODES["AZ"] == 109  # Diamondbacks (not "ARI")
    assert KALSHI_TEAM_CODES["WSH"] == 120  # Nationals (not "WSN")
    assert KALSHI_TEAM_CODES["KC"] == 118  # Royals (2-letter, not "KCR")
