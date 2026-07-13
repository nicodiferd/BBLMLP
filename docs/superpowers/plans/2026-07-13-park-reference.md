# Park Reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `park_reference` table joinable onto `games` via `games.venue`, giving `features/` a static, point-in-time-safe source of park context (altitude, roof type, dimensions, orientation), plus a repeatable `bblmlp check venues` command that catches sponsor renames/relocations before they silently mis-join.

**Architecture:** A new `src/bblmlp/ingest/mlb/park_reference.py` module holds two hand-curated dicts (`PARK_FACTS` keyed by canonical `park_id`, `VENUE_NAME_TO_PARK_ID` mapping every observed `games.venue` string to its `park_id`) and two pure functions (`find_unmapped_venues`, `build_park_reference`) — no network client, following the same seam as `team_crosswalk.py`. Two new CLI commands wire it in: `bblmlp build park-reference` (writes the table, raises on an unmapped venue) and `bblmlp check venues` (same check, reports instead of raising).

**Tech Stack:** pandas, DuckDB (`replace_all` for the full-table write), Typer CLI, pytest.

## Global Constraints

- No new network dependency — `PARK_FACTS`/`VENUE_NAME_TO_PARK_ID` are hand-curated Python literals, not fetched (same as `FANGRAPHS_ABBR_BY_TEAM_ID` in `team_crosswalk.py`).
- `find_unmapped_venues`/`build_park_reference` filter to `game_type == "R"` only — spring-training/exhibition venues are noise (per `docs/superpowers/specs/2026-07-13-park-reference-design.md` §2, same guard `team_crosswalk._derive_statcast_abbr` uses).
- `NULL` venue rows are excluded from the unmapped-venue check — a known, pre-existing data-quality gap (2 rows, 2021-2022), not a new venue to map.
- An unmapped regular-season venue makes `build_park_reference` raise `ValueError` naming the venue and pointing at the fix — never silently mis-join or drop (mirrors `team_crosswalk.build_team_crosswalk`'s existing error style).
- `park_reference` is a full-table replace (`replace_all`), not season-partitioned — park facts aren't season-scoped.
- Run tests with `uv run --no-sync pytest -q`, not bare `pytest` (CLAUDE.md's documented `.pth`/`UF_HIDDEN` gotcha).

---

### Task 1: `park_reference` table schema

**Files:**
- Modify: `src/bblmlp/storage/warehouse.py`
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Produces: a `park_reference` table with columns `venue` (VARCHAR PRIMARY KEY), `park_id` (VARCHAR NOT NULL), `park_name`, `altitude_ft`, `roof_type`, `lf_ft`, `cf_ft`, `rf_ft`, `orientation_deg`, `opened_year`. Task 2's `build_park_reference()` output DataFrame must use exactly these column names, in any order.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_warehouse.py` (after `test_init_schema_creates_tables`):

```python
def test_init_schema_creates_park_reference_table(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    assert "park_reference" in table_names(con)
    cols = [r[0] for r in con.execute("DESCRIBE park_reference").fetchall()]
    assert cols == [
        "venue", "park_id", "park_name", "altitude_ft", "roof_type",
        "lf_ft", "cf_ft", "rf_ft", "orientation_deg", "opened_year",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_warehouse.py::test_init_schema_creates_park_reference_table -v`
Expected: FAIL (`AssertionError` — `park_reference` not in table names, since the table doesn't exist yet)

- [ ] **Step 3: Write minimal implementation**

In `src/bblmlp/storage/warehouse.py`, add a new DDL constant after `TEAM_CROSSWALK_DDL` (around line 179):

```python
PARK_REFERENCE_DDL = """
CREATE TABLE IF NOT EXISTS park_reference (
    venue VARCHAR PRIMARY KEY,
    park_id VARCHAR NOT NULL,
    park_name VARCHAR,
    altitude_ft INTEGER,
    roof_type VARCHAR,
    lf_ft INTEGER,
    cf_ft INTEGER,
    rf_ft INTEGER,
    orientation_deg INTEGER,
    opened_year INTEGER
);
"""
```

Then add one line to `init_schema` (after `con.execute(TEAM_CROSSWALK_DDL)`):

```python
def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(GAMES_DDL)
    con.execute(STATCAST_DDL)
    con.execute(PLAYER_IDS_DDL)
    con.execute(PITCHER_GAME_DDL)
    con.execute(TEAM_GAME_DDL)
    con.execute(STANDINGS_DDL)
    con.execute(LIVE_LINEUPS_DDL)
    con.execute(TEAM_CROSSWALK_DDL)
    con.execute(PARK_REFERENCE_DDL)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_warehouse.py -v`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/storage/warehouse.py tests/test_warehouse.py
git commit -m "feat: add park_reference table schema"
```

---

### Task 2: `park_reference.py` — data + `find_unmapped_venues` + `build_park_reference`

**Files:**
- Create: `src/bblmlp/ingest/mlb/park_reference.py`
- Test: `tests/test_park_reference.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure, standalone module).
- Produces: `ParkFacts` (frozen dataclass), `PARK_FACTS: dict[str, ParkFacts]`, `VENUE_NAME_TO_PARK_ID: dict[str, str]`, `find_unmapped_venues(games: pd.DataFrame) -> set[str]`, `build_park_reference(games: pd.DataFrame) -> pd.DataFrame` — output columns exactly `["venue", "park_id", "park_name", "altitude_ft", "roof_type", "lf_ft", "cf_ft", "rf_ft", "orientation_deg", "opened_year"]`, matching Task 1's DDL. Tasks 3 and 4 both `from bblmlp.ingest.mlb.park_reference import build_park_reference, find_unmapped_venues`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_park_reference.py`:

```python
import pandas as pd
import pytest

from bblmlp.ingest.mlb.park_reference import (
    PARK_FACTS,
    VENUE_NAME_TO_PARK_ID,
    build_park_reference,
    find_unmapped_venues,
)


def _games(rows):
    return pd.DataFrame(rows, columns=["game_pk", "game_type", "venue"])


def test_find_unmapped_venues_ignores_non_regular_season_and_null_venue():
    games = _games([
        (1, "R", "Dodger Stadium"),      # mapped, regular season
        (2, "S", "Some Spring Complex"),  # unmapped, but spring training -> ignored
        (3, "R", None),                   # NULL venue, regular season -> ignored (known gap)
    ])
    assert find_unmapped_venues(games) == set()


def test_find_unmapped_venues_flags_unmapped_regular_season_venue():
    games = _games([
        (1, "R", "Dodger Stadium"),   # mapped
        (2, "R", "Some New Stadium"),  # unmapped, regular season -> flagged
    ])
    assert find_unmapped_venues(games) == {"Some New Stadium"}


def test_build_park_reference_produces_one_row_per_distinct_venue_with_facts():
    games = _games([
        (1, "R", "Dodger Stadium"),
        (2, "R", "Dodger Stadium"),  # same venue, second game -> still one row
        (3, "R", "Petco Park"),
    ])
    out = build_park_reference(games)
    assert len(out) == 2
    row = out[out["venue"] == "Dodger Stadium"].iloc[0]
    assert row["park_id"] == "dodger_stadium"
    assert row["altitude_ft"] == 492
    assert row["roof_type"] == "open"


def test_build_park_reference_resolves_sponsor_rename_to_same_park_id():
    games = _games([
        (1, "R", "Guaranteed Rate Field"),
        (2, "R", "Rate Field"),
    ])
    out = build_park_reference(games)
    assert set(out["park_id"]) == {"rate_field"}
    assert len(out) == 2  # two distinct venue strings, same park_id


def test_build_park_reference_treats_relocation_as_distinct_park_ids():
    # Oakland Coliseum (Athletics, 2021-2024) and Sutter Health Park (2025+)
    # are physically different parks -- must NOT collapse to one park_id
    # the way a sponsor rename does.
    games = _games([
        (1, "R", "Oakland Coliseum"),
        (2, "R", "Sutter Health Park"),
    ])
    out = build_park_reference(games)
    assert set(out["park_id"]) == {"oakland_coliseum", "sutter_health_park"}


def test_build_park_reference_treats_two_way_displacement_as_distinct_park_ids():
    # Tropicana Field and George M. Steinbrenner Field (Rays, 2025 only) are
    # both still valid -- Rays returned to Tropicana Field in 2026.
    games = _games([
        (1, "R", "Tropicana Field"),
        (2, "R", "George M. Steinbrenner Field"),
    ])
    out = build_park_reference(games)
    assert set(out["park_id"]) == {"tropicana_field", "steinbrenner_field"}


def test_neutral_site_venues_get_null_facts():
    games = _games([(1, "R", "Tokyo Dome")])
    out = build_park_reference(games)
    row = out.iloc[0]
    assert row["park_id"] == "neutral_site"
    assert pd.isna(row["altitude_ft"])
    assert pd.isna(row["roof_type"])


def test_build_park_reference_raises_on_unmapped_venue():
    games = _games([(1, "R", "Some New Stadium")])
    with pytest.raises(ValueError, match="Some New Stadium"):
        build_park_reference(games)


def test_every_venue_maps_to_a_defined_park_id():
    for venue, park_id in VENUE_NAME_TO_PARK_ID.items():
        assert park_id in PARK_FACTS, f"{venue!r} maps to undefined park_id {park_id!r}"


def test_park_facts_and_venue_map_counts():
    # 34 real parks + 1 neutral_site catch-all
    assert len(PARK_FACTS) == 35
    # 36 real venue strings (incl. 2 sponsor-rename pairs) + 9 neutral-site venues
    assert len(VENUE_NAME_TO_PARK_ID) == 45
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_park_reference.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bblmlp.ingest.mlb.park_reference'`

- [ ] **Step 3: Write the implementation**

Create `src/bblmlp/ingest/mlb/park_reference.py`:

```python
"""Static park reference: physical facts about each MLB park, joinable onto
`games` via `games.venue`.

`games.venue` carries StatsAPI's venue name for every game, including
spring-training/exhibition venues and one-off neutral-site special events
(London Series, Tokyo Series, etc.) that have no bearing on park-factor
modeling. `find_unmapped_venues` filters to regular-season games only, the
same guard `team_crosswalk.py` uses for Statcast abbreviations, so those
~30 spring-training venues never need mapping.

Physical parks are keyed by a stable `park_id`, not by venue name, because
the same park can appear under multiple `games.venue` strings over time
(sponsor renames: Guaranteed Rate Field -> Rate Field in 2025; Minute Maid
Park -> Daikin Park in 2025) -- and a relocation or temporary displacement
must NOT be collapsed the same way, since both venues stay independently
valid (Oakland Coliseum -> Sutter Health Park is a one-way move; Tropicana
Field <-> George M. Steinbrenner Field is a two-way, single-season
displacement, with the Rays back at Tropicana Field in 2026).
`VENUE_NAME_TO_PARK_ID` maps every observed venue string to its park_id;
`PARK_FACTS` holds one row of physical facts per park_id, hand-curated from
public references (Wikipedia ballpark pages, Baseball Reference park pages,
elevation APIs cross-referenced against park coordinates), not fetched.

One-off neutral-site special events (Rickwood Field, London Stadium, Tokyo
Dome, Gocheok Sky Dome, Estadio Alfredo Harp Helu, Bristol Motor Speedway,
BB&T Ballpark, Muncy Bank Ballpark, Journey Bank Ballpark) share
`park_id = "neutral_site"` with NULL facts rather than individually
researched trivia -- real venues, but not worth blocking the pipeline over
1-4 games each.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ParkFacts:
    park_name: str
    altitude_ft: int | None
    roof_type: str | None
    lf_ft: int | None
    cf_ft: int | None
    rf_ft: int | None
    orientation_deg: int | None
    opened_year: int | None


PARK_FACTS: dict[str, ParkFacts] = {
    "american_family_field": ParkFacts(park_name="American Family Field", altitude_ft=630, roof_type="retractable", lf_ft=344, cf_ft=400, rf_ft=345, orientation_deg=135, opened_year=2001),
    "angel_stadium": ParkFacts(park_name="Angel Stadium", altitude_ft=162, roof_type="open", lf_ft=347, cf_ft=396, rf_ft=350, orientation_deg=50, opened_year=1966),
    "busch_stadium": ParkFacts(park_name="Busch Stadium", altitude_ft=443, roof_type="open", lf_ft=336, cf_ft=400, rf_ft=335, orientation_deg=60, opened_year=2006),
    "chase_field": ParkFacts(park_name="Chase Field", altitude_ft=1135, roof_type="retractable", lf_ft=330, cf_ft=407, rf_ft=334, orientation_deg=0, opened_year=1998),
    "citi_field": ParkFacts(park_name="Citi Field", altitude_ft=21, roof_type="open", lf_ft=335, cf_ft=408, rf_ft=330, orientation_deg=35, opened_year=2009),
    "citizens_bank_park": ParkFacts(park_name="Citizens Bank Park", altitude_ft=11, roof_type="open", lf_ft=329, cf_ft=401, rf_ft=330, orientation_deg=18, opened_year=2004),
    "comerica_park": ParkFacts(park_name="Comerica Park", altitude_ft=617, roof_type="open", lf_ft=342, cf_ft=412, rf_ft=330, orientation_deg=145, opened_year=2000),
    "coors_field": ParkFacts(park_name="Coors Field", altitude_ft=5200, roof_type="open", lf_ft=347, cf_ft=415, rf_ft=350, orientation_deg=0, opened_year=1995),
    "daikin_park": ParkFacts(park_name="Daikin Park", altitude_ft=121, roof_type="retractable", lf_ft=315, cf_ft=409, rf_ft=326, orientation_deg=340, opened_year=2000),
    "dodger_stadium": ParkFacts(park_name="Dodger Stadium", altitude_ft=492, roof_type="open", lf_ft=330, cf_ft=395, rf_ft=330, orientation_deg=25, opened_year=1962),
    "fenway_park": ParkFacts(park_name="Fenway Park", altitude_ft=41, roof_type="open", lf_ft=310, cf_ft=390, rf_ft=302, orientation_deg=52, opened_year=1912),
    "globe_life_field": ParkFacts(park_name="Globe Life Field", altitude_ft=569, roof_type="retractable", lf_ft=329, cf_ft=407, rf_ft=326, orientation_deg=46, opened_year=2020),
    "great_american_ball_park": ParkFacts(park_name="Great American Ball Park", altitude_ft=528, roof_type="open", lf_ft=328, cf_ft=404, rf_ft=325, orientation_deg=115, opened_year=2003),
    "rate_field": ParkFacts(park_name="Rate Field", altitude_ft=617, roof_type="open", lf_ft=330, cf_ft=400, rf_ft=335, orientation_deg=120, opened_year=1991),
    "kauffman_stadium": ParkFacts(park_name="Kauffman Stadium", altitude_ft=906, roof_type="open", lf_ft=330, cf_ft=410, rf_ft=330, orientation_deg=48, opened_year=1973),
    "nationals_park": ParkFacts(park_name="Nationals Park", altitude_ft=16, roof_type="open", lf_ft=337, cf_ft=402, rf_ft=335, orientation_deg=30, opened_year=2008),
    "oracle_park": ParkFacts(park_name="Oracle Park", altitude_ft=25, roof_type="open", lf_ft=339, cf_ft=391, rf_ft=309, orientation_deg=87, opened_year=2000),
    "camden_yards": ParkFacts(park_name="Oriole Park at Camden Yards", altitude_ft=20, roof_type="open", lf_ft=333, cf_ft=400, rf_ft=318, orientation_deg=30, opened_year=1992),
    "pnc_park": ParkFacts(park_name="PNC Park", altitude_ft=719, roof_type="open", lf_ft=325, cf_ft=399, rf_ft=320, orientation_deg=120, opened_year=2001),
    "petco_park": ParkFacts(park_name="Petco Park", altitude_ft=16, roof_type="open", lf_ft=336, cf_ft=396, rf_ft=331, orientation_deg=0, opened_year=2004),
    "progressive_field": ParkFacts(park_name="Progressive Field", altitude_ft=681, roof_type="open", lf_ft=325, cf_ft=400, rf_ft=325, orientation_deg=356, opened_year=1994),
    "rogers_centre": ParkFacts(park_name="Rogers Centre", altitude_ft=299, roof_type="retractable", lf_ft=328, cf_ft=400, rf_ft=328, orientation_deg=0, opened_year=1989),
    "sutter_health_park": ParkFacts(park_name="Sutter Health Park", altitude_ft=31, roof_type="open", lf_ft=330, cf_ft=403, rf_ft=325, orientation_deg=65, opened_year=2000),
    "t_mobile_park": ParkFacts(park_name="T-Mobile Park", altitude_ft=39, roof_type="retractable", lf_ft=331, cf_ft=401, rf_ft=326, orientation_deg=45, opened_year=1999),
    "target_field": ParkFacts(park_name="Target Field", altitude_ft=828, roof_type="open", lf_ft=339, cf_ft=404, rf_ft=328, orientation_deg=90, opened_year=2010),
    "tropicana_field": ParkFacts(park_name="Tropicana Field", altitude_ft=115, roof_type="fixed_dome", lf_ft=315, cf_ft=404, rf_ft=322, orientation_deg=60, opened_year=1990),
    "truist_park": ParkFacts(park_name="Truist Park", altitude_ft=1025, roof_type="open", lf_ft=335, cf_ft=400, rf_ft=325, orientation_deg=135, opened_year=2017),
    "wrigley_field": ParkFacts(park_name="Wrigley Field", altitude_ft=602, roof_type="open", lf_ft=355, cf_ft=400, rf_ft=353, orientation_deg=30, opened_year=1914),
    "yankee_stadium": ParkFacts(park_name="Yankee Stadium", altitude_ft=26, roof_type="open", lf_ft=318, cf_ft=408, rf_ft=314, orientation_deg=55, opened_year=2009),
    "loandepot_park": ParkFacts(park_name="loanDepot park", altitude_ft=26, roof_type="retractable", lf_ft=344, cf_ft=400, rf_ft=335, orientation_deg=135, opened_year=2012),
    "oakland_coliseum": ParkFacts(park_name="Oakland Coliseum", altitude_ft=20, roof_type="open", lf_ft=330, cf_ft=400, rf_ft=330, orientation_deg=60, opened_year=1966),
    "sahlen_field": ParkFacts(park_name="Sahlen Field", altitude_ft=618, roof_type="open", lf_ft=325, cf_ft=404, rf_ft=325, orientation_deg=158, opened_year=1988),
    "td_ballpark": ParkFacts(park_name="TD Ballpark", altitude_ft=23, roof_type="open", lf_ft=333, cf_ft=400, rf_ft=336, orientation_deg=135, opened_year=1990),
    "steinbrenner_field": ParkFacts(park_name="George M. Steinbrenner Field", altitude_ft=46, roof_type="open", lf_ft=318, cf_ft=408, rf_ft=314, orientation_deg=60, opened_year=1996),
    "neutral_site": ParkFacts(park_name="Neutral site (one-off special event)", altitude_ft=None, roof_type=None, lf_ft=None, cf_ft=None, rf_ft=None, orientation_deg=None, opened_year=None),
}

VENUE_NAME_TO_PARK_ID: dict[str, str] = {
    "American Family Field": "american_family_field",
    "Angel Stadium": "angel_stadium",
    "Busch Stadium": "busch_stadium",
    "Chase Field": "chase_field",
    "Citi Field": "citi_field",
    "Citizens Bank Park": "citizens_bank_park",
    "Comerica Park": "comerica_park",
    "Coors Field": "coors_field",
    "Minute Maid Park": "daikin_park",
    "Daikin Park": "daikin_park",
    "Dodger Stadium": "dodger_stadium",
    "Fenway Park": "fenway_park",
    "Globe Life Field": "globe_life_field",
    "Great American Ball Park": "great_american_ball_park",
    "Guaranteed Rate Field": "rate_field",
    "Rate Field": "rate_field",
    "Kauffman Stadium": "kauffman_stadium",
    "Nationals Park": "nationals_park",
    "Oracle Park": "oracle_park",
    "Oriole Park at Camden Yards": "camden_yards",
    "PNC Park": "pnc_park",
    "Petco Park": "petco_park",
    "Progressive Field": "progressive_field",
    "Rogers Centre": "rogers_centre",
    "Sutter Health Park": "sutter_health_park",
    "T-Mobile Park": "t_mobile_park",
    "Target Field": "target_field",
    "Tropicana Field": "tropicana_field",
    "Truist Park": "truist_park",
    "Wrigley Field": "wrigley_field",
    "Yankee Stadium": "yankee_stadium",
    "loanDepot park": "loandepot_park",
    "Oakland Coliseum": "oakland_coliseum",
    "Sahlen Field": "sahlen_field",
    "TD Ballpark": "td_ballpark",
    "George M. Steinbrenner Field": "steinbrenner_field",
    # One-off neutral-site special events (<=4 games each) -- see module docstring.
    "BB&T Ballpark": "neutral_site",
    "Bristol Motor Speedway": "neutral_site",
    "Estadio Alfredo Harp Helu": "neutral_site",
    "Gocheok Sky Dome": "neutral_site",
    "Journey Bank Ballpark": "neutral_site",
    "London Stadium": "neutral_site",
    "Muncy Bank Ballpark": "neutral_site",
    "Rickwood Field": "neutral_site",
    "Tokyo Dome": "neutral_site",
}

_OUTPUT_COLUMNS = [
    "venue", "park_id", "park_name", "altitude_ft", "roof_type",
    "lf_ft", "cf_ft", "rf_ft", "orientation_deg", "opened_year",
]


def find_unmapped_venues(games: pd.DataFrame) -> set[str]:
    """Distinct regular-season venue strings not present in VENUE_NAME_TO_PARK_ID.

    Filters to game_type == 'R' (spring-training/exhibition venues are noise,
    the same guard team_crosswalk.py uses for Statcast abbreviations) and
    drops NULL venue rows (a known, separately-tracked data-quality gap, not
    a new venue to map).
    """
    regular = games[games["game_type"] == "R"]
    venues = set(regular["venue"].dropna().unique())
    return venues - set(VENUE_NAME_TO_PARK_ID.keys())


def build_park_reference(games: pd.DataFrame) -> pd.DataFrame:
    """One row per distinct regular-season venue: park_id + PARK_FACTS joined.

    Raises ValueError if a venue in `games` isn't in VENUE_NAME_TO_PARK_ID --
    likely a new venue, sponsor rename, or relocation; the message names the
    venue and points at the fix (mirrors team_crosswalk.py's error style).
    """
    unmapped = find_unmapped_venues(games)
    if unmapped:
        raise ValueError(
            f"Unmapped venue(s) found in regular-season games: {sorted(unmapped)}. "
            "Likely a new venue, sponsor rename, or relocation -- add an entry to "
            "VENUE_NAME_TO_PARK_ID (and PARK_FACTS if it's a genuinely new park)."
        )
    regular = games[games["game_type"] == "R"]
    venues = sorted(regular["venue"].dropna().unique())
    rows = []
    for venue in venues:
        park_id = VENUE_NAME_TO_PARK_ID[venue]
        facts = PARK_FACTS[park_id]
        rows.append({
            "venue": venue,
            "park_id": park_id,
            "park_name": facts.park_name,
            "altitude_ft": facts.altitude_ft,
            "roof_type": facts.roof_type,
            "lf_ft": facts.lf_ft,
            "cf_ft": facts.cf_ft,
            "rf_ft": facts.rf_ft,
            "orientation_deg": facts.orientation_deg,
            "opened_year": facts.opened_year,
        })
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_park_reference.py -v`
Expected: PASS (all 10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/mlb/park_reference.py tests/test_park_reference.py
git commit -m "feat: park_reference module (34 parks + venue-change guard)"
```

---

### Task 3: `bblmlp build park-reference` CLI command

**Files:**
- Modify: `src/bblmlp/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `build_park_reference` from Task 2 (`bblmlp.ingest.mlb.park_reference`); `connect`, `init_schema`, `replace_all` from `bblmlp.storage` (already exported).
- Produces: `bblmlp build park-reference` CLI command, no new Python interface for later tasks.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_build_group_has_park_reference_command():
    result = runner.invoke(app, ["build", "--help"])
    assert result.exit_code == 0
    assert "park-reference" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_cli.py::test_build_group_has_park_reference_command -v`
Expected: FAIL (`"park-reference" in result.stdout` is False — command not registered yet)

- [ ] **Step 3: Write the implementation**

In `src/bblmlp/cli.py`, add after `build_rollups` (end of file, before the `if __name__ == "__main__":` block):

```python
@build_app.command("park-reference")
def build_park_reference_cmd() -> None:
    """Build the park_reference table from games.venue (no --season: needs full history)."""
    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.park_reference import build_park_reference
    from bblmlp.storage import connect, init_schema, replace_all

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    games = con.execute("SELECT game_type, venue FROM games").df()
    out = build_park_reference(games)
    n = replace_all(con, "park_reference", out)
    con.close()
    typer.echo(f"Wrote {n} park_reference rows")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_cli.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/cli.py tests/test_cli.py
git commit -m "feat: bblmlp build park-reference CLI command"
```

---

### Task 4: `bblmlp check venues` CLI command

**Files:**
- Modify: `src/bblmlp/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `find_unmapped_venues` from Task 2.
- Produces: `bblmlp check venues` CLI command (new top-level `check` Typer group). Exit code 0 if no unmapped venues, 1 otherwise.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
def _game_row(venue: str) -> dict:
    return {
        "game_pk": 1, "season": 2025, "game_type": "R", "game_date": "2025-07-04",
        "game_datetime": "2025-07-04T18:05:00Z", "home_team": "Dodgers", "away_team": "Giants",
        "home_team_id": 119, "away_team_id": 137,
        "home_probable_pitcher": None, "away_probable_pitcher": None,
        "home_probable_pitcher_id": None, "away_probable_pitcher_id": None,
        "venue": venue, "status": "Final", "home_score": 5, "away_score": 3, "home_win": 1,
    }


def test_check_group_has_venues_command():
    result = runner.invoke(app, ["check", "--help"])
    assert result.exit_code == 0
    assert "venues" in result.stdout


def test_check_venues_exits_zero_when_all_mapped(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from bblmlp.storage import connect, init_schema, upsert_games

    warehouse = tmp_path / "w.duckdb"
    con = connect(warehouse)
    init_schema(con)
    upsert_games(con, [_game_row("Dodger Stadium")])
    con.close()

    fake_settings = SimpleNamespace(data=SimpleNamespace(warehouse_path=warehouse))
    monkeypatch.setattr("bblmlp.config.load_settings", lambda *a, **k: fake_settings)

    result = runner.invoke(app, ["check", "venues"])
    assert result.exit_code == 0
    assert result.stdout == ""


def test_check_venues_exits_one_and_lists_unmapped_venue(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from bblmlp.storage import connect, init_schema, upsert_games

    warehouse = tmp_path / "w.duckdb"
    con = connect(warehouse)
    init_schema(con)
    upsert_games(con, [_game_row("Some New Stadium")])
    con.close()

    fake_settings = SimpleNamespace(data=SimpleNamespace(warehouse_path=warehouse))
    monkeypatch.setattr("bblmlp.config.load_settings", lambda *a, **k: fake_settings)

    result = runner.invoke(app, ["check", "venues"])
    assert result.exit_code == 1
    assert "Some New Stadium" in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_cli.py -v`
Expected: FAIL — no `check` group registered yet, so all three new tests fail (the `--help` test on a missing-group usage error; the two functional tests the same way, since `["check", "venues"]` isn't a valid command path yet)

- [ ] **Step 3: Write the implementation**

In `src/bblmlp/cli.py`, add the new Typer group near the top (after `build_app = typer.Typer(...)` and its `app.add_typer` call, around line 8):

```python
check_app = typer.Typer(help="Repeatable data-quality checks against the warehouse.")
app.add_typer(check_app, name="check")
```

Then add the command anywhere after that (e.g. at the end of the file, after `build_park_reference_cmd`):

```python
@check_app.command("venues")
def check_venues_cmd() -> None:
    """Report any games.venue string not yet mapped in park_reference (sponsor rename/relocation guard)."""
    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.park_reference import find_unmapped_venues
    from bblmlp.storage import connect, init_schema

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    games = con.execute("SELECT game_type, venue FROM games").df()
    con.close()
    unmapped = find_unmapped_venues(games)
    if not unmapped:
        raise typer.Exit(code=0)
    for venue in sorted(unmapped):
        typer.echo(venue)
    raise typer.Exit(code=1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_cli.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/cli.py tests/test_cli.py
git commit -m "feat: bblmlp check venues CLI command"
```

---

### Task 5: End-to-end verification against the real warehouse

**Files:** none (no code changes — this task verifies Tasks 1-4 against real data per the design doc's success criteria)

**Interfaces:** none produced.

- [ ] **Step 1: Build the real park_reference table**

Run: `uv run --no-sync bblmlp build park-reference` (fall back to `PYTHONPATH=src .venv/bin/python -m bblmlp.cli build park-reference` if the console script hits the `.pth` gotcha)
Expected: `Wrote 45 park_reference rows` (36 real-park venue strings + 9 neutral-site venue strings; no `ValueError` raised, since every 2021-2025 regular-season venue is covered)

- [ ] **Step 2: Confirm `check venues` is clean**

Run: `uv run --no-sync bblmlp check venues; echo "exit code: $?"`
Expected: no output, `exit code: 0`

- [ ] **Step 3: Spot-check a few rows directly**

Run:
```bash
PYTHONPATH=src .venv/bin/python -c "
import duckdb
con = duckdb.connect('data/warehouse.duckdb', read_only=True)
print(con.execute(\"SELECT * FROM park_reference WHERE park_id IN ('coors_field', 'rate_field', 'oakland_coliseum', 'sutter_health_park', 'tropicana_field', 'steinbrenner_field', 'neutral_site') ORDER BY park_id, venue\").df())
"
```
Expected: `coors_field` shows `altitude_ft=5200`; `rate_field` appears twice (once per venue string: `Guaranteed Rate Field`, `Rate Field`) both with `park_id='rate_field'`; `oakland_coliseum` and `sutter_health_park` are distinct rows with distinct facts; `tropicana_field` and `steinbrenner_field` are distinct rows; `neutral_site` rows show `NULL` for `altitude_ft`/`roof_type`/dimensions.

- [ ] **Step 4: Simulate a new/renamed venue and confirm the guard fires**

Run:
```bash
PYTHONPATH=src .venv/bin/python -c "
import pandas as pd
from bblmlp.ingest.mlb.park_reference import build_park_reference
games = pd.DataFrame([{'game_type': 'R', 'venue': 'Totally New Stadium'}])
try:
    build_park_reference(games)
    print('FAIL: should have raised')
except ValueError as e:
    print('OK, raised:', e)
"
```
Expected: `OK, raised: Unmapped venue(s) found in regular-season games: ['Totally New Stadium']. ...`

No commit for this task (verification only, no code changes).
