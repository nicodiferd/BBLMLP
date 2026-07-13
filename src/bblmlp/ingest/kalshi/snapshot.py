"""Pure normalizer/matcher for Kalshi KXMLBGAME markets. No network calls -- everything
here takes already-fetched API payloads (dicts) and our own `games` DataFrame, and is
unit-tested with fixtures.
"""
from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

import pandas as pd

from bblmlp.ingest.kalshi.team_map import KALSHI_TEAM_CODES

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


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def normalize_snapshot(
    markets: list[dict],
    orderbooks: dict[str, dict],
    games_df: pd.DataFrame,
    pulled_at: str,
) -> pd.DataFrame:
    """Turn raw Kalshi market + orderbook payloads into `kalshi_quotes` rows.

    Never drops a row for a failed join or an unmapped team code (e.g. the
    All-Star game's AL/NL) -- price data is irreplaceable (Kalshi has no
    history API), so it's always persisted with game_pk/team_id as NULL when
    they can't be resolved.
    """
    pulled_at_ts = pd.Timestamp(pulled_at)
    rows = []
    for market in markets:
        parsed = parse_market_ticker(market)
        team_code = parsed["kalshi_team_code"]
        other_code = parsed["other_team_code"]
        team_id = KALSHI_TEAM_CODES.get(team_code)
        other_team_id = KALSHI_TEAM_CODES.get(other_code)

        game_pk = None
        if team_id is not None and other_team_id is not None:
            home_team_id = team_id if parsed["is_home"] else other_team_id
            away_team_id = other_team_id if parsed["is_home"] else team_id
            game_pk = match_game_pk(
                games_df, parsed["game_date"], home_team_id, away_team_id,
                game_number=parsed["game_number"], hhmm_et=parsed["hhmm_et"],
            )

        yes_bid = _to_float(market.get("yes_bid_dollars"))
        yes_ask = _to_float(market.get("yes_ask_dollars"))
        book = orderbooks.get(market["ticker"], {}).get("orderbook_fp", {})

        rows.append({
            "pulled_at": pulled_at_ts,
            "event_ticker": market["event_ticker"],
            "market_ticker": market["ticker"],
            "game_pk": game_pk,
            "kalshi_team_code": team_code,
            "is_home": parsed["is_home"],
            "team_id": team_id,
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_bid": _to_float(market.get("no_bid_dollars")),
            "no_ask": _to_float(market.get("no_ask_dollars")),
            "spread": None if yes_bid is None or yes_ask is None else round(yes_ask - yes_bid, 4),
            "volume_fp": _to_float(market.get("volume_fp")),
            "open_interest_fp": _to_float(market.get("open_interest_fp")),
            "status": market.get("status"),
            "yes_book_json": json.dumps(book.get("yes_dollars", [])),
            "no_book_json": json.dumps(book.get("no_dollars", [])),
        })

    return pd.DataFrame(rows, columns=[
        "pulled_at", "event_ticker", "market_ticker", "game_pk", "kalshi_team_code",
        "is_home", "team_id", "yes_bid", "yes_ask", "no_bid", "no_ask", "spread",
        "volume_fp", "open_interest_fp", "status", "yes_book_json", "no_book_json",
    ])
