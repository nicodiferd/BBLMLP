"""One-off: record a real StatsAPI schedule response for test fixtures.

Run manually:  uv run python scripts/capture_schedule_fixture.py
"""
import json
from pathlib import Path

import statsapi

# A date known to have completed MLB games.
games = statsapi.schedule(start_date="2024-07-04", end_date="2024-07-04")
out = Path("tests/fixtures/statsapi_schedule.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(games, indent=2, default=str))
print(f"Wrote {len(games)} games to {out}")
