"""Kalshi's own 2-3 letter team codes -> StatsAPI team_id.

Kalshi team codes don't match any other source's abbreviations (e.g. `ATH` not `OAK`,
`AZ` not `ARI`, `WSH` not `WSN`, `KC`/`SD`/`SF`/`TB` are 2 letters). Neither derivable
nor documented anywhere but Kalshi's own API, so this is a hand-maintained static map --
same pattern as `ingest/mlb/team_crosswalk.py`'s `FANGRAPHS_ABBR_BY_TEAM_ID`, except
`team_id` is relocation-proof (doesn't shift the way an abbreviation does), so no
season-scoped override list is needed here.

Enumerated by pulling every KXMLBGAME market live (`GET /markets?series_ticker=KXMLBGAME
&limit=1000`) on 2026-07-12 -- see
docs/superpowers/specs/2026-07-12-kalshi-snapshot-ingest-design.md #2.1 for the full
derivation (each code's `yes_sub_title` cross-referenced against `team_crosswalk`'s
2025 team names).
"""
from __future__ import annotations

KALSHI_TEAM_CODES: dict[str, int] = {
    "AZ": 109, "ATH": 133, "ATL": 144, "BAL": 110, "BOS": 111,
    "CHC": 112, "CIN": 113, "CLE": 114, "COL": 115, "CWS": 145,
    "DET": 116, "HOU": 117, "KC": 118, "LAA": 108, "LAD": 119,
    "MIA": 146, "MIL": 158, "MIN": 142, "NYM": 121, "NYY": 147,
    "PHI": 143, "PIT": 134, "SD": 135, "SEA": 136, "SF": 137,
    "STL": 138, "TB": 139, "TEX": 140, "TOR": 141, "WSH": 120,
}
