"""Pure normalizer/matcher for Kalshi KXMLBGAME markets. No network calls -- everything
here takes already-fetched API payloads (dicts) and our own `games` DataFrame, and is
unit-tested with fixtures.
"""
from __future__ import annotations

import datetime as dt

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_market_ticker(market: dict) -> dict:
    """Parse one KXMLBGAME market's ticker fields.

    Ticker grammar: `KXMLBGAME-{YY}{MMM}{DD}{HHMM}{AWAY}{HOME}[G{N}]-{TEAM}`. `HHMM` is
    the game's originally-scheduled first-pitch time in America/New_York wall-clock,
    frozen at market-creation time (confirmed empirically against MLB StatsAPI --
    NOT UTC, despite the earlier discovery doc's claim; see the design doc's #2).

    The market's own team code (`ticker`'s trailing segment) is matched against the
    event slug's `{AWAY}{HOME}` blob as a prefix or suffix -- unambiguous, no guessing,
    and works even for team codes outside `KALSHI_TEAM_CODES` (e.g. All-Star `AL`/`NL`).
    """
    ticker = market["ticker"]
    event_ticker = market["event_ticker"]
    team_code = ticker.rsplit("-", 1)[-1]
    slug = event_ticker.split("-", 1)[1]  # e.g. "26JUL121610TORSD"

    yy, mmm, dd, hhmm = slug[0:2], slug[2:5], slug[5:7], slug[7:11]
    teams_blob = slug[11:]  # e.g. "TORSD" or "MILSTLG1"

    game_number = None
    if teams_blob[-2:] in ("G1", "G2"):
        game_number = int(teams_blob[-1])
        teams_blob = teams_blob[:-2]

    if teams_blob.startswith(team_code):
        other_team_code = teams_blob[len(team_code):]
        is_home = False
    elif teams_blob.endswith(team_code):
        other_team_code = teams_blob[:-len(team_code)]
        is_home = True
    else:
        raise ValueError(
            f"team code {team_code!r} not found in ticker slug {teams_blob!r} "
            f"(ticker={ticker!r})"
        )

    return {
        "game_date": dt.date(2000 + int(yy), _MONTHS[mmm], int(dd)),
        "hhmm_et": hhmm,
        "game_number": game_number,
        "kalshi_team_code": team_code,
        "other_team_code": other_team_code,
        "is_home": is_home,
    }
