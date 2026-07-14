import datetime as dt

import duckdb

from bblmlp.ingest.kalshi.ingest import pull_and_snapshot
from bblmlp.storage import init_schema, upsert_games


def _fake_markets():
    return [
        {
            "ticker": "KXMLBGAME-26JUL121610TORSD-TOR",
            "event_ticker": "KXMLBGAME-26JUL121610TORSD",
            "status": "active",
            "yes_bid_dollars": "0.4600", "yes_ask_dollars": "0.4700",
            "no_bid_dollars": "0.5300", "no_ask_dollars": "0.5400",
            "volume_fp": "23083.00", "open_interest_fp": "1000.00",
        },
        {
            "ticker": "KXMLBGAME-26JUL121610TORSD-SD",
            "event_ticker": "KXMLBGAME-26JUL121610TORSD",
            "status": "active",
            "yes_bid_dollars": "0.5300", "yes_ask_dollars": "0.5400",
            "no_bid_dollars": "0.4600", "no_ask_dollars": "0.4700",
            "volume_fp": "15059.00", "open_interest_fp": "900.00",
        },
    ]


def _fake_orderbook(_ticker):
    return {"orderbook_fp": {"yes_dollars": [["0.5300", "100.00"]], "no_dollars": [["0.4600", "50.00"]]}}


def _game_row():
    return {
        "game_pk": 999001, "season": 2026, "game_date": "2026-07-12",
        "game_datetime": "2026-07-12T20:10:00Z", "home_team": "San Diego Padres",
        "away_team": "Toronto Blue Jays", "home_team_id": 135, "away_team_id": 141,
        "home_probable_pitcher": None, "away_probable_pitcher": None,
        "venue": "Petco Park", "status": "Scheduled",
        "home_score": None, "away_score": None, "home_win": None,
    }


def test_pull_and_snapshot_writes_rows_and_parquet(tmp_path):
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    init_schema(con)
    upsert_games(con, [_game_row()])

    n = pull_and_snapshot(
        con, tmp_path / "snapshots",
        fetch_markets=lambda series="KXMLBGAME": _fake_markets(),
        fetch_book=_fake_orderbook,
        pulled_at=dt.datetime(2026, 7, 12, 12, 0, 0, tzinfo=dt.timezone.utc),
    )

    assert n == 2
    assert con.execute("SELECT count(*) FROM kalshi_quotes").fetchone()[0] == 2
    matched = con.execute(
        "SELECT count(*) FROM kalshi_quotes WHERE game_pk = 999001"
    ).fetchone()[0]
    assert matched == 2

    parquet_files = list((tmp_path / "snapshots").glob("*.parquet"))
    assert len(parquet_files) == 1
    # Read back via DuckDB itself, not pandas -- pd.read_parquet needs a pyarrow/
    # fastparquet engine, and the design deliberately avoids a pyarrow dependency
    # (DuckDB writes and reads Parquet natively; see design doc's #2.5).
    roundtrip_count = duckdb.sql(
        f"SELECT count(*) FROM read_parquet('{parquet_files[0]}')"
    ).fetchone()[0]
    assert roundtrip_count == 2


def test_pull_and_snapshot_second_call_appends_not_replaces(tmp_path):
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    init_schema(con)
    upsert_games(con, [_game_row()])

    kwargs = dict(
        fetch_markets=lambda series="KXMLBGAME": _fake_markets(),
        fetch_book=_fake_orderbook,
    )
    pull_and_snapshot(con, tmp_path / "snapshots", pulled_at=dt.datetime(2026, 7, 12, 12, 0, 0, tzinfo=dt.timezone.utc), **kwargs)
    pull_and_snapshot(con, tmp_path / "snapshots", pulled_at=dt.datetime(2026, 7, 12, 12, 30, 0, tzinfo=dt.timezone.utc), **kwargs)

    assert con.execute("SELECT count(*) FROM kalshi_quotes").fetchone()[0] == 4
    assert len(list((tmp_path / "snapshots").glob("*.parquet"))) == 2
