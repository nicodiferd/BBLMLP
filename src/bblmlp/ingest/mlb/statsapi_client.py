"""Thin wrapper over MLB-StatsAPI. The only place that touches the network."""
from __future__ import annotations

import datetime as _dt

import statsapi


def month_ranges(start_date: str, end_date: str) -> list[tuple[str, str]]:
    """Split an inclusive [start, end] date range into <=1-calendar-month chunks.

    MLB StatsAPI returns 502 on very large hydrated schedule requests (a full
    season in one call), so schedule fetches are chunked by month. Chunks are
    contiguous and cover exactly [start, end] with no gaps or overlaps.
    """
    start = _dt.date.fromisoformat(start_date)
    end = _dt.date.fromisoformat(end_date)
    ranges: list[tuple[str, str]] = []
    cur = start
    while cur <= end:
        if cur.month == 12:
            month_end = _dt.date(cur.year, 12, 31)
        else:
            month_end = _dt.date(cur.year, cur.month + 1, 1) - _dt.timedelta(days=1)
        chunk_end = min(month_end, end)
        ranges.append((cur.isoformat(), chunk_end.isoformat()))
        cur = chunk_end + _dt.timedelta(days=1)
    return ranges


def fetch_schedule(start_date: str, end_date: str) -> list[dict]:
    """Return raw StatsAPI schedule dicts for the inclusive date range.

    Chunked by month to avoid 502s on large full-season requests.
    """
    games: list[dict] = []
    for s, e in month_ranges(start_date, end_date):
        games.extend(statsapi.schedule(start_date=s, end_date=e))
    return games
