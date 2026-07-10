# MLB Data Ingest — Comprehensive Data Layer (Service 1 completion)

> Design doc · 2026-07-09 · Status: **draft, awaiting user review**
> Deepens Service 1 of `2026-07-09-bblmlp-single-game-betting-design.md`.

## 1. Goal

Turn the MLB data ingest from a thin schedule+narrow-Statcast pull into the **complete,
model-ready data layer** the game-winner model needs — landing raw facts faithfully so
feature engineering (Service 2) has everything it needs and we **never have to re-backfill
to recover a dropped field.**

This is the "tier B / comprehensive, depth-first" option: Statcast-centric core + external
season-level context (FanGraphs, standings) + a live daily pull for today's starters/lineups.

**Success criteria:**
- A single `bblmlp ingest all --backfill` lands every table below for the configured seasons, idempotently and re-runnably.
- The full Statcast column set is stored (not a 12-column subset).
- Every Statcast pitcher/batter id resolves to a name and FanGraphs id via a crosswalk.
- Historical starters + lineups are derivable without per-game boxscore calls.
- Each source has a unit-tested pure normalizer and a schema-contract test.

## 2. Design principles

- **Land raw, faithfully.** Ingest stores facts at their natural grain (pitch, game, season). Rolling windows, "as-of" alignment, and model features are **Service 2's** job, not Service 1's. Ingest never computes a leakage-sensitive rolling stat.
- **Keep everything from Statcast.** Storage is cheap (DuckDB columnar); re-backfilling is the expensive operation. Store the full pybaseball Statcast schema so no future feature is blocked by a dropped column.
- **Derive before you call.** Anything computable from data already landed (historical starters, lineups, team game lines) is derived, not re-fetched. External API calls are reserved for what can't be derived (season context, *today's* pre-game lineups).
- **Idempotent per source.** Every writer is keyed and re-runnable: re-ingesting a season replaces that season's rows, never appends duplicates (the pattern already used for `statcast_pitches` and `games`).

## 3. Data sources → tables

| # | Table | Grain | Source | New? |
|---|---|---|---|---|
| 1 | `games` | game | StatsAPI schedule | exists (enrich) |
| 2 | `statcast_pitches` | pitch | pybaseball `statcast()` | exists (**widen to full schema**) |
| 3 | `player_ids` | player | pybaseball `chadwick_register()` | **new** |
| 4 | `team_batting_season` | team-season | pybaseball `team_batting()` | **new** |
| 5 | `team_pitching_season` | team-season | pybaseball `team_pitching()` | **new** |
| 6 | `pitcher_stats_season` | player-season | pybaseball `pitching_stats()` | **new** |
| 7 | `batter_stats_season` | player-season | pybaseball `batting_stats()` | **new** |
| 8 | `standings` | team-season | StatsAPI `standings_data()` | **new** |
| 9 | `pitcher_game_stats` | pitcher-game | derived from `statcast_pitches` | **new (derived)** |
| 10 | `team_game_stats` | team-game | derived from `statcast_pitches` | **new (derived)** |
| 11 | `live_lineups` | player-game | StatsAPI boxscore/probables (**today only**) | **new (live)** |

### 3.1 `statcast_pitches` — widen to the full schema
Today we keep 12 of ~90 columns. **Store the complete Statcast column set.** The DDL is generated
from the known pybaseball Statcast schema (stable superset), and the normalizer enforces types on
the identity/key columns (`game_pk`, ids, dates) and passes the rest through. Column families that
unlock features and are currently discarded:
- **Handedness:** `stand`, `p_throws`
- **Count/state:** `balls`, `strikes`, `outs_when_up`, `inning`, `inning_topbot`, `on_1b/2b/3b`
- **Pitch:** `pitch_name`, `type` (B/S/X), `zone`, `release_speed`, `effective_speed`, `release_spin_rate`, `spin_axis`, `pfx_x/z`, `plate_x/z`, `release_pos_x/z`, `release_extension`
- **Contact:** `bb_type`, `launch_speed`, `launch_angle`, `hit_distance_sc`, `launch_speed_angle` (barrel 1–6)
- **Value:** `woba_value`, `woba_denom`, `babip_value`, `iso_value`, `estimated_woba_using_speedangle`, `estimated_ba_using_speedangle`, `delta_run_exp`, `delta_home_win_exp`
- **Score state:** `home_team`, `away_team`, `bat_score`, `fld_score`, `home_score`, `away_score`

Widening does **not** increase fetch time — the full payload is already downloaded; we simply stop dropping columns.

### 3.2 `player_ids` — the join backbone
Chadwick register crosswalk: `key_mlbam`, `key_fangraphs`, `key_bbref`, `key_retro`, `name_first`,
`name_last`, `mlb_played_first`, `mlb_played_last`. This is what lets us join Statcast (MLBAM ids) ↔
FanGraphs season stats (FanGraphs ids) ↔ probable-pitcher **names** from the schedule. Static-ish;
refreshed on demand. `games` gets enriched with `home_probable_pitcher_id` / `away_probable_pitcher_id`
resolved through this table (best-effort name match).

### 3.3 FanGraphs season tables (4, 5, 6, 7)
Season-grain context that Statcast pitch data can't express directly: team `wRC+`, `wOBA`, bullpen
`ERA`/`FIP`, park factors (team tables); pitcher `FIP`/`xFIP`/`SIERA`/`K%`/`BB%` and batter
`wRC+`/`ISO` (player tables). One pybaseball call per season per table — cheap. Keyed by
`(season, team)` or `(season, key_fangraphs)`.

> **Leakage note (for Service 2, recorded here):** these are *full-season* aggregates and include
> games that hadn't happened yet at any mid-season point. Service 2 must consume them point-in-time
> — e.g., prior-season value early, rolling/as-of thereafter — never the raw current-season row as a
> pre-game feature. Ingest lands them as-is; the guard lives in features.

### 3.4 `standings`
Team W-L, win%, GB, streak, run differential per season (and by date for live). Mostly derivable from
`games`, but StatsAPI gives it directly and cheaply; landed for convenience and cross-checks.

### 3.5 Derived game-grain rollups (9, 10)
Deterministic aggregates of `statcast_pitches` at **this-game grain** (no rolling windows → no
leakage):
- `pitcher_game_stats`: per `(game_pk, pitcher)` — pitches, batters faced, K, BB, whiffs, CSW%, xwOBA-against, avg velo, is_starter (first pitcher for their fielding side).
- `team_game_stats`: per `(game_pk, team)` — PA, xwOBA, K%, BB%, hard-hit%, runs.

The `is_starter` flag + batting-order-by-first-`at_bat_number` is how we **derive historical starters
and lineups from Statcast**, avoiding ~12k boxscore backfill calls.

### 3.6 `live_lineups` (today only)
For same-day prediction, Statcast doesn't exist pre-game. A daily `bblmlp ingest live` pulls
StatsAPI probable pitchers + posted lineups for **today's** slate into `live_lineups`. Small volume
(~15 games/day). Historical backfill of this table is **out of scope** (derive from Statcast instead).

## 4. Idempotency & backfill strategy

| Source | Key / replace unit | Cost |
|---|---|---|
| `statcast_pitches` | replace by `season` | high fetch (already exists), unchanged by widening |
| FanGraphs tables | replace by `season` | 1 call/season/table — cheap |
| `player_ids` | full replace | 1 call — cheap |
| `standings` | replace by `season` | cheap |
| derived rollups | replace by `season`, rebuilt from local Statcast | no network |
| `live_lineups` | replace by `game_date` | cheap, today only |

`pybaseball` calls are wrapped with a polite throttle + its built-in cache. `bblmlp ingest all
--backfill` runs sources in dependency order: `players` → `statcast` → `fangraphs`/`standings` →
derived rollups.

## 5. CLI surface

```
bblmlp ingest players                 # refresh the Chadwick crosswalk
bblmlp ingest statcast --season 2024  # (widened) pitch data
bblmlp ingest fangraphs --season 2024 # team + player season tables
bblmlp ingest standings --season 2024
bblmlp build rollups --season 2024    # derive pitcher_game_stats + team_game_stats
bblmlp ingest live                    # today's probables + lineups
bblmlp ingest all --backfill          # everything, all configured seasons, in order
bblmlp ingest all --date 2026-07-09   # everything relevant for one live day
```

## 6. Code structure

Extends `src/bblmlp/ingest/mlb/`, following the existing fetch→normalize→write seam (network client
separate from pure normalizers, orchestrator takes fetch fns as params for fixture-injected tests):
- `statcast.py` — widen schema (DDL + normalizer).
- `players.py` — crosswalk fetch + normalize + write.
- `fangraphs.py` — the four season tables.
- `standings.py`.
- `rollups.py` — pure SQL/pandas derivations over `statcast_pitches`.
- `live.py` — today's lineups/probables.
- `storage/warehouse.py` — DDL for all new tables + per-season replace writers.
- `cli.py` — the subcommands above.

## 7. Testing strategy

- **Pure normalizer unit tests** per source, driven by small captured fixtures (extend the
  `tests/fixtures/` pattern already used for the schedule).
- **Schema-contract tests**: each table has the expected columns/types after `init_schema`.
- **Idempotency tests**: ingest a season twice → row count stable, no dupes (mirrors existing
  statcast/games tests).
- **Derivation tests**: `is_starter` and lineup-order logic against a hand-built mini Statcast frame
  with a known starter and batting order.
- **Crosswalk join test**: a probable-pitcher name resolves to the right MLBAM id.
- Network `fetch_*` functions stay thin and are not unit-tested (integration-checked manually).

## 8. Risks / open items

1. **Boxscore-free historical starters.** Deriving `is_starter`/lineups from Statcast assumes the
   first pitch faced/thrown identifies the starter and leadoff order — true in practice; a derivation
   test pins it. Opener/bullpen-game edge cases are acceptable (the "starter" is still whoever threw
   first).
2. **FanGraphs season-stat leakage** — handled in Service 2, flagged in §3.3. Ingest must not be used
   as a pre-game feature source without the as-of guard.
3. **Crosswalk name collisions** (e.g., two "Luis Garcia") — resolve with team + active-years from
   the crosswalk; leave unresolved ids null rather than guessing.
4. **Statcast re-backfill runtime** — widening requires one re-backfill of the configured seasons
   (fetch time unchanged; only storage grows). Run once; idempotent thereafter.
5. **pybaseball/FanGraphs rate limits** — polite throttle + cache; season-grain calls are few.

## 9. Out of scope (this spec)

- As-of feature engineering and the model (Service 2/3 — next spec).
- Kalshi ingest + crafter (Service 4/5 — deferred per today's plan).
- Historical boxscore/lineup backfill (derived from Statcast instead).
- Splits (vs L/R), weather, umpires, minor-league (tier C — YAGNI).
