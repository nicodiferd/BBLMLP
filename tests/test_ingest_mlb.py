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
