# Park Reference — static park facts + venue-change guard

> Design doc · 2026-07-13 · Status: **approved, ready for planning**
> New feature-family addition alongside the research-backlog's `features/` step (roadmap
> `docs/roadmap/2026-07-11-research-backlog.md`, #4-#7). Not itself one of the numbered issues —
> a standalone extension identified in a separate brainstorming session, sequenced to land
> independently of that backlog's build order.

## 1. Goal

Give `features/` a static, point-in-time-safe source of park context (altitude, roof type,
dimensions, orientation) joinable onto any `games` row via `games.venue` — no new network
ingest source, since the join key already exists in the warehouse.

**Explicitly two different things, and this spec covers only the first:**
- **(A) Static park attributes** — hand-curated facts about each physical park. Buildable now,
  standalone, zero dependency on unbuilt work. **In scope here.**
- **(B) The empirical park factor** (the actual run/HR-scoring multiplier vs. a neutral park,
  computed from trailing outcomes) — belongs on top of #4's trailing-window machinery once that
  exists, reusing `park_id` from (A) as its join key so sponsor-renamed-but-same-park data pools
  correctly. **Out of scope here**, tracked as follow-on work.

**Success criteria:**
- Every regular-season `games` row joins to exactly one `park_reference` row via `venue`.
- A sponsor rename, relocation, or new venue in freshly-ingested data is caught immediately —
  either by `bblmlp build park-reference` refusing to build, or by running `bblmlp check venues`
  on demand — never silently mis-joined or silently dropped.
- Physical facts are only hand-researched for parks worth the effort (recurring team homes);
  one-off neutral-site games don't block the pipeline over unresearched trivia.

## 2. Empirically validated findings (checked against the live warehouse 2026-07-13)

- **`games.venue` already exists and is populated** — `ingest/mlb/schedule.py:63` sets it from
  `raw.get("venue_name")` for every ingested game. No new network client needed for the join key.
- **The `games` table's non-regular-season rows pollute venue counts badly**, the same trap
  `team_crosswalk.py` already guards against for team abbreviations: 76 distinct venues across
  all `game_type`s, dropping to **46 when filtered to `game_type = 'R'`** — the other 30 are
  spring-training facilities (Cactus/Grapefruit League parks) and minor-league affiliate parks
  used for taxi-squad/rehab games. `find_unmapped_venues` filters to regular season for the same
  reason `_derive_statcast_abbr` does.
- **Even at 46, there's a long tail below the 30 primary team-home parks:**
  - Known **sponsor renames mid-window**: `Guaranteed Rate Field` (2021-2024) → `Rate Field`
    (2025+, White Sox); `Minute Maid Park` (2021-2024) → `Daikin Park` (2025+, Astros).
  - Known **relocations**: `Oakland Coliseum` (2021-2024) → `Sutter Health Park` (2025+,
    Athletics, Sacramento); `Tropicana Field` → `George M. Steinbrenner Field` (2025 only, Rays,
    hurricane damage) — note `Tropicana Field` still appears through 2026 in the data, so this is
    a temporary displacement, not a permanent move; venue mapping must not assume one-way.
  - Known **temporary 2021 COVID-era homes** (Blue Jays, before returning to Rogers Centre):
    `Sahlen Field` (Buffalo), `TD Ballpark` (Dunedin spring facility), `BB&T Ballpark` (Charlotte,
    1 game).
  - **One-off neutral-site special events**, 1-4 games each, low/no recurrence likelihood:
    `London Stadium`, `Tokyo Dome`, `Gocheok Sky Dome` (Seoul Series), `Estadio Alfredo Harp Helu`
    (Mexico City Series), `Rickwood Field` (2024 tribute game), `Bristol Motor Speedway` (2025
    Speedway Classic), `Muncy Bank Ballpark` / `Journey Bank Ballpark` (Little League Classic,
    Williamsport-area).
  - **2 rows with `venue IS NULL`** (2021-2022) — a pre-existing data-quality gap, not a new
    stadium to research.

**Scope decision from these findings:** full physical-fact research (altitude, roof, dimensions,
orientation) covers only the ~32 parks that are or were a recurring team home (the 30 current
parks + Sahlen Field + Steinbrenner Field; sponsor-renamed parks reuse the same `park_id` as their
prior name). One-off neutral-site venues get a shared `park_id = "neutral_site"` with `NULL`
facts rather than individual research — real but low-value data, not worth blocking the pipeline
over. `NULL` venue rows are excluded from `find_unmapped_venues` entirely (already a known gap,
tracked separately, not a new venue).

## 3. Module layout

New `src/bblmlp/ingest/mlb/park_reference.py`, alongside `team_crosswalk.py`. No network client —
like `FANGRAPHS_ABBR_BY_TEAM_ID`, this is hand-curated from public references (Wikipedia's MLB
ballpark pages, Baseball Reference park factor pages) rather than fetched. Two module-level dicts,
same shape as `team_crosswalk.py`'s override pattern:

- **`PARK_FACTS: dict[str, ParkFacts]`** — keyed by canonical `park_id` (e.g. `"rate_field"`,
  `"coors_field"`, `"neutral_site"`). One entry per physical park, not per venue name.
- **`VENUE_NAME_TO_PARK_ID: dict[str, str]`** — every distinct `games.venue` string ever observed
  (including sponsor-rename variants) mapped to its canonical `park_id`. This is where
  `"Guaranteed Rate Field"` and `"Rate Field"` both point at the same `park_id`.

Functions:
- **`find_unmapped_venues(games: pd.DataFrame) -> set[str]`** — pure function. Filters to
  `game_type == "R"`, drops `NULL` venue, returns the set difference against
  `VENUE_NAME_TO_PARK_ID`'s keys. No DB connection — takes an already-fetched DataFrame, matching
  the `team_crosswalk.py` testing convention.
- **`build_park_reference(games: pd.DataFrame) -> pd.DataFrame`** — calls `find_unmapped_venues`
  internally and raises `ValueError` (message names the unmapped venue(s) and instructs adding a
  `VENUE_NAME_TO_PARK_ID`/`PARK_FACTS` entry, mirroring `team_crosswalk.py`'s existing error
  message style) if non-empty. Otherwise returns one row per distinct regular-season venue: the
  venue string plus its `park_id` and joined `PARK_FACTS`.

## 4. Data model

**`park_reference`** (new DuckDB table, full-replace on rebuild — not season-partitioned, since
park facts aren't season-scoped the way `team_crosswalk` is; a rename just adds a new `venue` row
pointing at an existing `park_id`).

| column | type | notes |
|---|---|---|
| `venue` | VARCHAR | exact string from `games.venue` — the join key consumers use |
| `park_id` | VARCHAR | canonical id, stable across sponsor renames — the join key (B) will use later |
| `park_name` | VARCHAR | current/display name |
| `altitude_ft` | INTEGER | nullable for `neutral_site` |
| `roof_type` | VARCHAR | `open` / `fixed_dome` / `retractable` |
| `lf_ft`, `cf_ft`, `rf_ft` | INTEGER | nullable for `neutral_site` |
| `orientation_deg` | INTEGER | home-plate-to-center-field azimuth; nullable for `neutral_site` |
| `opened_year` | INTEGER | nullable for `neutral_site` |

## 5. CLI

- **`bblmlp build park-reference`** — added to the existing `build_app` group (alongside
  `team-crosswalk`, `rollups`). No `--season` option, unlike its siblings — it needs the full
  history of distinct venues, not a season slice. Reads `games`, calls `build_park_reference`,
  writes the table (full replace). Raises loudly (per §3) if an unmapped venue is found — this is
  the build-time guard.
- **`bblmlp check venues`** (new top-level command, not under `build_app` — it's a report, not a
  build step) — reads `games` from the warehouse, calls `find_unmapped_venues`, and:
  - prints nothing and exits `0` if the set is empty,
  - prints each unmapped venue and exits `1` otherwise.
  Non-destructive, safe to run anytime — after a daily live ingest, at the start of a new season,
  or on a periodic cron — without requiring a full `build park-reference` run. This is the
  repeatable stadium-change check.

## 6. Testing

Fixture-based, no network, no DB connection needed for the pure functions (matches
`team_crosswalk.py`'s test style):
- `find_unmapped_venues`: a `games` fixture with a mix of `game_type` values confirms
  spring-training/exhibition venues are excluded even if unmapped; a `NULL`-venue row is excluded;
  a genuinely unmapped regular-season venue is returned; an all-mapped fixture returns empty.
- `build_park_reference`: an all-mapped fixture produces one correct row per distinct venue with
  the right `park_id`/facts joined, including two differently-named venues resolving to the same
  `park_id` (sponsor-rename case); an unmapped-venue fixture raises `ValueError` with a message
  naming the offending venue.
- CLI: `check venues` exit code and output on both a clean and a dirty fixture warehouse.

## 7. Explicitly out of scope

- The empirical/trailing park factor multiplier (B in §1) — deferred to ride on #4's window
  machinery once built, using `park_id` as the stable join key.
- Weather/wind-effect features — orientation is captured here as raw context but no weather
  ingestion is part of this spec.
- Backfilling `NULL` venue rows (2 known rows, 2021-2022) — pre-existing gap, not this spec's job.
- Any automated seeding of `PARK_FACTS`/`VENUE_NAME_TO_PARK_ID` from an external API — this data
  is hand-researched once from public references, same as `FANGRAPHS_ABBR_BY_TEAM_ID`.

## 8. Open risk carried forward

`Tropicana Field` / `George M. Steinbrenner Field` is a **two-way** relocation (Rays are back at
Tropicana Field per the 2026 schedule already in `games`), unlike the Athletics' one-way move to
Sacramento. `VENUE_NAME_TO_PARK_ID` must map both venue strings to their own distinct `park_id`s
(they're physically different parks, both still valid, not a rename-of-one) — worth calling out
explicitly during implementation so it isn't collapsed into a single `park_id` by analogy with the
sponsor-rename cases.
