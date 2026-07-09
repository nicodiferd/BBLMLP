import json
from pathlib import Path

from bblmlp.ingest.mlb.ingest import ingest_range
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
