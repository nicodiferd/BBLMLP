import json
from pathlib import Path

from bblmlp.ingest.mlb.ingest import ingest_range, ingest_seasons, season_date_range
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
