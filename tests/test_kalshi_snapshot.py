import datetime as dt
import json

import pandas as pd
import pytest

from bblmlp.ingest.kalshi.snapshot import match_game_pk, normalize_snapshot, parse_market_ticker


def test_parse_market_ticker_away_side():
    market = {
        "ticker": "KXMLBGAME-26JUL121610TORSD-TOR",
        "event_ticker": "KXMLBGAME-26JUL121610TORSD",
    }
    parsed = parse_market_ticker(market)
    assert parsed["game_date"] == dt.date(2026, 7, 12)
    assert parsed["hhmm_et"] == "1610"
    assert parsed["game_number"] is None
    assert parsed["kalshi_team_code"] == "TOR"
    assert parsed["other_team_code"] == "SD"
    assert parsed["is_home"] is False


def test_parse_market_ticker_home_side():
    market = {
        "ticker": "KXMLBGAME-26JUL121610TORSD-SD",
        "event_ticker": "KXMLBGAME-26JUL121610TORSD",
    }
    parsed = parse_market_ticker(market)
    assert parsed["kalshi_team_code"] == "SD"
    assert parsed["other_team_code"] == "TOR"
    assert parsed["is_home"] is True


def test_parse_market_ticker_doubleheader_suffix():
    market = {
        "ticker": "KXMLBGAME-26JUL071415MILSTLG1-MIL",
        "event_ticker": "KXMLBGAME-26JUL071415MILSTLG1",
    }
    parsed = parse_market_ticker(market)
    assert parsed["game_number"] == 1
    assert parsed["kalshi_team_code"] == "MIL"
    assert parsed["other_team_code"] == "STL"
    assert parsed["is_home"] is False


def test_parse_market_ticker_all_star_codes_not_in_team_map():
    # AL/NL aren't real franchises (not in KALSHI_TEAM_CODES) but the ticker
    # still parses structurally -- team_id resolution happens later, in normalize_snapshot.
    market = {
        "ticker": "KXMLBGAME-26JUL142000ALNL-NL",
        "event_ticker": "KXMLBGAME-26JUL142000ALNL",
    }
    parsed = parse_market_ticker(market)
    assert parsed["kalshi_team_code"] == "NL"
    assert parsed["other_team_code"] == "AL"
    assert parsed["is_home"] is True


def _games_df(rows):
    return pd.DataFrame(rows, columns=["game_pk", "game_date", "game_datetime", "home_team_id", "away_team_id"])


def test_match_game_pk_single_candidate():
    games = _games_df([
        [824816, "2026-07-09", "2026-07-09 17:35:00", 110, 112],
    ])
    assert match_game_pk(games, dt.date(2026, 7, 9), 110, 112) == 824816


def test_match_game_pk_no_candidates_returns_none():
    games = _games_df([[824816, "2026-07-09", "2026-07-09 17:35:00", 110, 112]])
    assert match_game_pk(games, dt.date(2026, 7, 10), 110, 112) is None


def test_match_game_pk_doubleheader_disambiguated_by_game_number():
    # Real doubleheader from our own warehouse: Twins (home, 142) vs Guardians
    # (away, 114) on 2025-09-20 -- two actual games, confirmed via a direct query
    # during the design pass (see design doc's #6 testing section).
    games = _games_df([
        [777839, "2025-09-20", "2025-09-20 18:10:00", 142, 114],
        [776243, "2025-09-20", "2025-09-20 23:10:00", 142, 114],
    ])
    assert match_game_pk(games, dt.date(2025, 9, 20), 142, 114, game_number=1) == 777839
    assert match_game_pk(games, dt.date(2025, 9, 20), 142, 114, game_number=2) == 776243


def test_match_game_pk_doubleheader_disambiguated_by_closest_et_time():
    games = _games_df([
        [777839, "2025-09-20", "2025-09-20 18:10:00", 142, 114],  # 14:10 ET
        [776243, "2025-09-20", "2025-09-20 23:10:00", 142, 114],  # 19:10 ET
    ])
    assert match_game_pk(games, dt.date(2025, 9, 20), 142, 114, hhmm_et="1410") == 777839
    assert match_game_pk(games, dt.date(2025, 9, 20), 142, 114, hhmm_et="1910") == 776243


def test_match_game_pk_ambiguous_doubleheader_with_no_disambiguator_returns_none():
    games = _games_df([
        [777839, "2025-09-20", "2025-09-20 18:10:00", 142, 114],
        [776243, "2025-09-20", "2025-09-20 23:10:00", 142, 114],
    ])
    assert match_game_pk(games, dt.date(2025, 9, 20), 142, 114) is None


def _market(ticker, event_ticker, **overrides):
    base = {
        "ticker": ticker,
        "event_ticker": event_ticker,
        "status": "active",
        "yes_bid_dollars": "0.5400",
        "yes_ask_dollars": "0.5500",
        "no_bid_dollars": "0.4500",
        "no_ask_dollars": "0.4600",
        "volume_fp": "15059.00",
        "open_interest_fp": "2851507.04",
    }
    base.update(overrides)
    return base


def _orderbook():
    return {"orderbook_fp": {
        "yes_dollars": [["0.5300", "2270.43"], ["0.5400", "1427.94"]],
        "no_dollars": [["0.4500", "6404.00"], ["0.4600", "1236.38"]],
    }}


def _games_df_for_torsd():
    return pd.DataFrame([
        # TOR (away, 141) @ SD (home, 135), 2026-07-12, ticker HHMM=1610 ET -> 20:10 UTC
        [999001, "2026-07-12", "2026-07-12 20:10:00", 135, 141],
    ], columns=["game_pk", "game_date", "game_datetime", "home_team_id", "away_team_id"])


def test_normalize_snapshot_produces_matched_row_for_away_and_home_sides():
    markets = [
        _market("KXMLBGAME-26JUL121610TORSD-TOR", "KXMLBGAME-26JUL121610TORSD"),
        _market("KXMLBGAME-26JUL121610TORSD-SD", "KXMLBGAME-26JUL121610TORSD",
                yes_bid_dollars="0.4500", yes_ask_dollars="0.4600"),
    ]
    orderbooks = {
        "KXMLBGAME-26JUL121610TORSD-TOR": _orderbook(),
        "KXMLBGAME-26JUL121610TORSD-SD": _orderbook(),
    }
    df = normalize_snapshot(markets, orderbooks, _games_df_for_torsd(), "2026-07-12T12:00:00+00:00")

    assert len(df) == 2
    tor = df[df["kalshi_team_code"] == "TOR"].iloc[0]
    sd = df[df["kalshi_team_code"] == "SD"].iloc[0]

    assert tor["game_pk"] == 999001 and sd["game_pk"] == 999001
    # Not an `is True/False` identity check: a row pulled via `.iloc[0]` can come
    # back as numpy.bool_, which isn't the same object as Python's True/False.
    assert not tor["is_home"] and sd["is_home"]
    assert tor["team_id"] == 141 and sd["team_id"] == 135
    assert tor["yes_bid"] == 0.54 and tor["yes_ask"] == 0.55
    assert tor["spread"] == pytest.approx(0.01)
    assert json.loads(tor["yes_book_json"]) == [["0.5300", "2270.43"], ["0.5400", "1427.94"]]


def test_normalize_snapshot_unmapped_team_code_keeps_row_with_null_game_pk():
    # All-Star game: AL/NL aren't in KALSHI_TEAM_CODES. Price data must still be
    # persisted (never drop a row) with game_pk/team_id as NULL.
    markets = [_market("KXMLBGAME-26JUL142000ALNL-NL", "KXMLBGAME-26JUL142000ALNL")]
    orderbooks = {"KXMLBGAME-26JUL142000ALNL-NL": _orderbook()}
    df = normalize_snapshot(markets, orderbooks, pd.DataFrame(
        columns=["game_pk", "game_date", "game_datetime", "home_team_id", "away_team_id"]
    ), "2026-07-12T12:00:00+00:00")

    assert len(df) == 1
    row = df.iloc[0]
    assert row["kalshi_team_code"] == "NL"
    assert row["is_home"]  # still derivable from ticker position (not an `is True` identity check)
    assert pd.isna(row["team_id"])
    assert pd.isna(row["game_pk"])
    assert row["yes_bid"] == 0.54  # price data preserved regardless


def test_normalize_snapshot_missing_orderbook_leaves_book_columns_empty():
    markets = [_market("KXMLBGAME-26JUL121610TORSD-TOR", "KXMLBGAME-26JUL121610TORSD")]
    df = normalize_snapshot(markets, {}, _games_df_for_torsd(), "2026-07-12T12:00:00+00:00")
    assert df.iloc[0]["yes_book_json"] == "[]"
    assert df.iloc[0]["no_book_json"] == "[]"
