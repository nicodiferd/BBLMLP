import datetime as dt

import pandas as pd

from bblmlp.ingest.kalshi.snapshot import match_game_pk, parse_market_ticker


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
