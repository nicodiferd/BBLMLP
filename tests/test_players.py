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

def test_normalize_players_drops_sentinel_null_and_duplicate_mlbam():
    # Real Chadwick register uses -1 (and can carry NaN) for players with no
    # MLBAM id; many such rows must not collide on the key_mlbam PRIMARY KEY.
    raw = pd.DataFrame({
        "key_mlbam": [111, -1, -1, float("nan"), 222, 222],
        "key_fangraphs": [11, 91, 92, 93, 22, 23],
        "key_bbref": ["a", "b", "c", "d", "e", "f"],
        "key_retro": ["r1", "r2", "r3", "r4", "r5", "r6"],
        "name_first": ["Ryan", "No", "No", "Na", "Luis", "Luis"],
        "name_last": ["Feltner", "M1", "M2", "Nan", "Garcia", "Garcia"],
        "mlb_played_first": [2021, 2000, 2001, 2002, 2010, 2010],
        "mlb_played_last": [2026, 2005, 2006, 2007, 2016, 2016],
    })
    out = normalize_players(raw)
    assert list(out["key_mlbam"]) == [111, 222]   # -1 + NaN dropped, 222 de-duped
    assert out["key_mlbam"].is_unique
    assert out["key_mlbam"].dtype == "int64"


def test_resolve_unique_name():
    assert resolve_player_id(_people(), "Ryan", "Feltner") == 111

def test_resolve_ambiguous_name_uses_active_year():
    # two Luis Garcias; the 2024-active one is key_mlbam 333
    assert resolve_player_id(_people(), "Luis", "Garcia", active_year=2024) == 333

def test_resolve_unresolvable_returns_none():
    assert resolve_player_id(_people(), "Nobody", "Here") is None
