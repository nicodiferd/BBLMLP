import pandas as pd
from bblmlp.ingest.mlb.players import normalize_players, resolve_player_id

def _people():
    return pd.DataFrame({
        "key_mlbam": [111, 222, 333],
        "key_fangraphs": [11, 22, 33],
        "key_bbref": ["a", "b", "c"], "key_retro": ["r1","r2","r3"],
        "name_first": ["Ryan", "Luis", "Luis"], "name_last": ["Feltner","Garcia","Garcia"],
        "mlb_played_first": [2021, 2010, 2022], "mlb_played_last": [2026, 2016, 2026],
    })

def test_normalize_players_selects_crosswalk_columns():
    out = normalize_players(_people())
    assert list(out.columns)[:2] == ["key_mlbam", "key_fangraphs"]
    assert out["key_mlbam"].dtype == "int64"

def test_resolve_unique_name():
    assert resolve_player_id(_people(), "Ryan", "Feltner") == 111

def test_resolve_ambiguous_name_uses_active_year():
    # two Luis Garcias; the 2024-active one is key_mlbam 333
    assert resolve_player_id(_people(), "Luis", "Garcia", active_year=2024) == 333

def test_resolve_unresolvable_returns_none():
    assert resolve_player_id(_people(), "Nobody", "Here") is None
