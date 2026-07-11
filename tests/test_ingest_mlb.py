import json
from pathlib import Path

from bblmlp.ingest.mlb.ingest import ingest_all, ingest_range, ingest_seasons, season_date_range
from bblmlp.storage import connect, init_schema

RAW = json.loads(Path("tests/fixtures/statsapi_schedule.json").read_text())


def test_ingest_range_writes_games(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)

    def fake_fetch(start_date, end_date):
        return RAW

    written = ingest_range(con, fake_fetch, "2024-07-04", "2024-07-04", season=2024)
    assert written == len(RAW)
    count = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    assert count == len(RAW)


def test_ingest_range_is_idempotent(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)

    def fake_fetch(start_date, end_date):
        return RAW

    ingest_range(con, fake_fetch, "2024-07-04", "2024-07-04", season=2024)
    ingest_range(con, fake_fetch, "2024-07-04", "2024-07-04", season=2024)
    count = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    assert count == len(RAW)


def test_season_date_range():
    assert season_date_range(2024) == ("2024-03-01", "2024-11-30")


def test_ingest_seasons_calls_fetch_per_season(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    calls = []

    def fake_fetch(start_date, end_date):
        calls.append((start_date, end_date))
        return RAW  # reuse fixture; pks collide across seasons but upsert dedupes

    ingest_seasons(con, fake_fetch, [2023, 2024])
    assert calls == [("2023-03-01", "2023-11-30"), ("2024-03-01", "2024-11-30")]


def test_ingest_all_runs_sources_in_order_with_injected_fetchers(tmp_path):
    con = connect(tmp_path / "wh.duckdb"); init_schema(con)
    import pandas as pd
    fetchers = {
        "chadwick": lambda: pd.DataFrame({"key_mlbam":[111],"key_fangraphs":[11],
            "key_bbref":["a"],"key_retro":["r"],"name_first":["Ryan"],
            "name_last":["Feltner"],"mlb_played_first":[2021],"mlb_played_last":[2026]}),
        "schedule": lambda s, e: [{"game_id":1,"game_date":f"{s[:4]}-05-01","home_name":"SF",
            "away_name":"COL","status":"Final","home_score":3,"away_score":1}],
    }
    class S:  # minimal settings stub
        class data: warehouse_path=str(tmp_path/"wh.duckdb"); backfill_seasons=[2024]
    counts = ingest_all(con, S, fetchers=fetchers)
    assert counts["players"] == 1
    assert counts["games"] >= 1
    assert con.execute("SELECT count(*) FROM games").fetchone()[0] >= 1


def test_ingest_all_runs_rollups_when_statcast_and_rollups_keys_present(tmp_path):
    con = connect(tmp_path / "wh.duckdb"); init_schema(con)
    import pandas as pd

    def fake_statcast(season):
        return pd.DataFrame({
            "game_pk": [1, 1, 1, 1],
            "season": [season] * 4,
            "inning_topbot": ["Top", "Top", "Bot", "Bot"],
            "home_team": ["SF"] * 4, "away_team": ["COL"] * 4,
            "pitcher": [500, 500, 900, 900],
            "batter": [10, 11, 20, 21],
            "at_bat_number": [1, 2, 3, 4],
            "pitch_number": [1, 1, 1, 1],
            "events": ["strikeout", "walk", "single", "field_out"],
            "description": ["swinging_strike", "ball", "hit_into_play", "hit_into_play"],
            "estimated_woba_using_speedangle": [0.0, 0.0, 0.9, 0.1],
            "release_speed": [95, 96, 93, 92],
        })

    fetchers = {
        "chadwick": lambda: pd.DataFrame({"key_mlbam":[111],"key_fangraphs":[11],
            "key_bbref":["a"],"key_retro":["r"],"name_first":["Ryan"],
            "name_last":["Feltner"],"mlb_played_first":[2021],"mlb_played_last":[2026]}),
        "schedule": lambda s, e: [{"game_id":1,"game_date":f"{s[:4]}-05-01","home_name":"SF",
            "away_name":"COL","status":"Final","home_score":3,"away_score":1}],
        "statcast": fake_statcast,
        "rollups": True,
    }
    class S:  # minimal settings stub
        class data: warehouse_path=str(tmp_path/"wh.duckdb"); backfill_seasons=[2024]

    counts = ingest_all(con, S, fetchers=fetchers)
    assert counts["rollups"] >= 1
    assert con.execute("SELECT count(*) FROM pitcher_game_stats").fetchone()[0] >= 1
    assert con.execute("SELECT count(*) FROM team_game_stats").fetchone()[0] >= 1


def test_ingest_all_builds_team_crosswalk_when_keys_present(tmp_path):
    con = connect(tmp_path / "wh.duckdb"); init_schema(con)
    import pandas as pd

    def fake_statcast(season):
        return pd.DataFrame({
            "game_pk": [744834],  # matches RAW fixture's game_id
            "season": [season],
            "home_team": ["WSH"], "away_team": ["NYM"],
            "inning_topbot": ["Top"],
            "pitcher": [500], "batter": [10],
            "at_bat_number": [1], "pitch_number": [1],
            "events": [None], "description": ["ball"],
            "estimated_woba_using_speedangle": [0.0], "release_speed": [95],
        })

    def fake_standings(season):
        return {200: {"teams": [
            {"team_id": 120, "name": "Washington Nationals", "w": 1, "l": 0},
            {"team_id": 121, "name": "New York Mets", "w": 0, "l": 1},
        ]}}

    fetchers = {
        "chadwick": lambda: pd.DataFrame({"key_mlbam":[111],"key_fangraphs":[11],
            "key_bbref":["a"],"key_retro":["r"],"name_first":["Ryan"],
            "name_last":["Feltner"],"mlb_played_first":[2021],"mlb_played_last":[2026]}),
        "schedule": lambda s, e: RAW,
        "statcast": fake_statcast,
        "standings": fake_standings,
        "team_crosswalk": True,
    }
    class S:  # minimal settings stub
        class data: warehouse_path=str(tmp_path/"wh.duckdb"); backfill_seasons=[2024]

    counts = ingest_all(con, S, fetchers=fetchers)
    assert counts["team_crosswalk"] == 2
    rows = con.execute(
        "SELECT team_id, statcast_abbr FROM team_crosswalk WHERE season = 2024 ORDER BY team_id"
    ).fetchall()
    assert rows == [(120, "WSH"), (121, "NYM")]
