"""Thin wrapper over MLB-StatsAPI. The only place that touches the network."""
from __future__ import annotations

import statsapi


def fetch_schedule(start_date: str, end_date: str) -> list[dict]:
    """Return raw StatsAPI schedule dicts for the inclusive date range."""
    return statsapi.schedule(start_date=start_date, end_date=end_date)
