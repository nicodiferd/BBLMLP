from bblmlp.ingest.mlb.standings import normalize_standings


def test_normalize_standings_flattens_divisions():
    raw = {  # shape of statsapi.standings_data(): {division_id: {"teams": [...]}}
        200: {"teams": [
            {"team_id": 137, "name": "SF", "w": 90, "l": 72, "gb": "-",
             "div_rank": "1", "streak": "W2"},
        ]},
    }
    rows = normalize_standings(raw, season=2024)
    assert rows.iloc[0]["team_id"] == 137
    assert rows.iloc[0]["w"] == 90
    assert rows.iloc[0]["season"] == 2024
