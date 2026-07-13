import datetime as dt

from bblmlp.ingest.kalshi.snapshot import parse_market_ticker


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
