"""Pure normalizer/matcher for Kalshi KXMLBGAME markets. No network calls -- everything
here takes already-fetched API payloads (dicts) and our own `games` DataFrame, and is
unit-tested with fixtures.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd

_ET = ZoneInfo("America/New_York")

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


def match_game_pk(
    games_df: "pd.DataFrame",
    game_date: dt.date,
    home_team_id: int,
    away_team_id: int,
    *,
    game_number: int | None = None,
    hhmm_et: str | None = None,
) -> int | None:
    """Join a Kalshi market to our `games` table by date + team ids.

    Handles doubleheaders (>1 candidate row): prefers the explicit `game_number`
    (from a `G1`/`G2` ticker suffix) when given, else picks the candidate whose
    `game_datetime` converts to America/New_York wall-clock closest to `hhmm_et`.
    Returns None (never raises) when there's no candidate, or when there's more
    than one and no disambiguator was given -- callers must persist the price
    row anyway with game_pk=NULL rather than drop it (see design doc's core
    "never drop a row" principle).
    """
    gd = pd.to_datetime(games_df["game_date"]).dt.date
    mask = (
        (gd == game_date)
        & (games_df["home_team_id"] == home_team_id)
        & (games_df["away_team_id"] == away_team_id)
    )
    candidates = games_df[mask]
    if len(candidates) == 0:
        return None
    if len(candidates) == 1:
        return int(candidates.iloc[0]["game_pk"])

    candidates = candidates.sort_values("game_datetime")

    if game_number is not None:
        idx = game_number - 1
        if 0 <= idx < len(candidates):
            return int(candidates.iloc[idx]["game_pk"])
        return None

    if hhmm_et is not None:
        target = int(hhmm_et)

        def _et_hhmm(value) -> int:
            local = pd.Timestamp(value).tz_localize("UTC").tz_convert(_ET)
            return local.hour * 100 + local.minute

        diffs = candidates["game_datetime"].map(lambda v: abs(_et_hhmm(v) - target))
        return int(candidates.loc[diffs.idxmin(), "game_pk"])

    return None
