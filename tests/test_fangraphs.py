import pandas as pd
from bblmlp.ingest.mlb.fangraphs import normalize_team_batting, normalize_team_pitching

def test_team_batting_tidies_and_tags_season():
    raw = pd.DataFrame({"Team": ["SFG"], "wRC+": [105], "wOBA": [0.320], "HR": [180]})
    out = normalize_team_batting(raw, season=2024)
    assert out["season"].iloc[0] == 2024
    assert "wrc_plus" in out.columns and out["wrc_plus"].iloc[0] == 105
    assert "team" in out.columns

def test_team_pitching_tidies_and_tags_season():
    raw = pd.DataFrame({"Team": ["SFG"], "FIP": [3.9], "ERA": [3.8], "K/9": [9.1]})
    out = normalize_team_pitching(raw, season=2024)
    assert out["season"].iloc[0] == 2024
    assert "fip" in out.columns
