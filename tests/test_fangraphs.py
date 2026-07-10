import duckdb
import pandas as pd
from bblmlp.ingest.mlb.fangraphs import (
    normalize_batter_stats,
    normalize_pitcher_stats,
    normalize_team_batting,
    normalize_team_pitching,
)
from bblmlp.storage import ensure_table_from_df, replace_partition

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

def test_snake_case_avoids_collisions_and_leading_digits():
    # Real FanGraphs team-pitching/batting columns that historically collided
    # (ERA vs ERA-, FIP vs FIP-, xFIP vs xFIP-) or produced invalid unquoted
    # SQL identifiers (1B/2B/3B start with a digit).
    raw = pd.DataFrame({
        "Team": ["SFG"],
        "ERA": [3.8], "ERA-": [95],
        "FIP": [3.9], "FIP-": [97],
        "xFIP": [4.0], "xFIP-": [99],
        "1B": [900], "2B": [300], "3B": [30],
        "wRC+": [105], "K%": [0.23],
    })

    pitching = normalize_team_pitching(raw, season=2024)
    batting = normalize_team_batting(raw, season=2024)

    for out in (pitching, batting):
        cols = list(out.columns)
        # (a) no collisions
        assert len(cols) == len(set(cols)), f"duplicate columns: {cols}"
        # (b) no output column starts with a digit (valid SQL identifiers)
        for c in cols:
            assert not c[0].isdigit(), f"invalid identifier: {c}"
        # (c) specific expected mappings
        for expected in (
            "era", "era_minus", "fip", "fip_minus", "xfip", "xfip_minus",
            "_1b", "_2b", "_3b", "wrc_plus", "k_pct",
        ):
            assert expected in cols, f"missing expected column {expected!r} in {cols}"

def test_snake_case_output_actually_writes_to_duckdb():
    # Integration check: the collision/parser crashes reproduced against real
    # FanGraphs data must actually be gone at the DuckDB write layer.
    raw = pd.DataFrame({
        "Team": ["SFG"],
        "ERA": [3.8], "ERA-": [95],
        "FIP": [3.9], "FIP-": [97],
        "xFIP": [4.0], "xFIP-": [99],
        "1B": [900], "2B": [300], "3B": [30],
        "wRC+": [105], "K%": [0.23],
    })
    out = normalize_team_pitching(raw, season=2024)

    con = duckdb.connect(":memory:")
    ensure_table_from_df(con, "fg_team_pitching", out)
    replace_partition(con, "fg_team_pitching", out, "season")

    assert con.execute("SELECT count(*) FROM fg_team_pitching").fetchone()[0] == 1

def test_pitcher_stats_preserve_fangraphs_id_and_tag_season():
    raw = pd.DataFrame({"IDfg": [22], "Name": ["A B"], "K%": [0.30], "xFIP": [3.5]})
    out = normalize_pitcher_stats(raw, season=2024)
    assert out["season"].iloc[0] == 2024
    assert "key_fangraphs" in out.columns and out["key_fangraphs"].iloc[0] == 22
    assert "k_pct" in out.columns

def test_batter_stats_preserve_fangraphs_id():
    raw = pd.DataFrame({"IDfg": [11], "Name": ["C D"], "wRC+": [140], "ISO": [0.25]})
    out = normalize_batter_stats(raw, season=2024)
    assert out["key_fangraphs"].iloc[0] == 11
    assert "wrc_plus" in out.columns
