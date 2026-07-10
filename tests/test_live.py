from bblmlp.ingest.mlb.live import normalize_live_lineups


def test_normalize_live_lineups_flattens_probables_and_order():
    raw = [{
        "game_id": 7, "home_name": "SF", "away_name": "COL",
        "home_probable_pitcher_id": 500, "away_probable_pitcher_id": 900,
        "home_lineup": [{"player_id": 10, "order": 1}, {"player_id": 11, "order": 2}],
        "away_lineup": [{"player_id": 20, "order": 1}],
    }]
    out = normalize_live_lineups(raw, game_date="2026-07-09")
    probs = out[out["is_probable_pitcher"]]
    assert set(probs["player_id"]) == {500, 900}
    sf = out[(out["team"] == "SF") & (~out["is_probable_pitcher"])].sort_values("batting_order")
    assert list(sf["player_id"]) == [10, 11]
    assert (out["game_date"] == "2026-07-09").all()
