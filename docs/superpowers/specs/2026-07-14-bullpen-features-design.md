# Bullpen Features (exact, not by subtraction)

> Design doc · 2026-07-14 · Status: **approved, ready for planning**
> Roadmap issue #5 (`docs/roadmap/2026-07-11-research-backlog.md`, Step 2 — `features/`).
> Builds directly on #4's rolling-window machinery (`docs/superpowers/specs/2026-07-13-rolling-window-features-design.md`).

## 1. Goal

Add team-level bullpen strength as a rolling-window feature, computed *exactly* from
`pitcher_game_stats` rows where `is_starter == False` — no subtract-starter-from-team-totals
hack, no innings/outs remainder logic. Per the roadmap, bullpen features were the single biggest
model improvement in the research series this backlog is based on.

**Out of scope for this spec:**
- Cold-start / shrinkage priors (#6) — partial windows are left as DuckDB naturally computes them,
  same as #4.
- Batter/lineup features (#7) — unrelated, blocked on the separate `#2` lineup spike.
- Joining `bullpen_features` onto `games` via `team_crosswalk` — deferred to whichever consumer
  assembles the model training frame (e.g. #8), same convention #4 already established for
  `team_features`. This table stays keyed by Statcast abbreviation, not `team_id`.

## 2. Prerequisite fix — `pitcher_game_stats` gains a `team` column

`pitcher_game_stats` (`src/bblmlp/ingest/mlb/rollups.py`) currently computes each pitcher's
fielding team internally (`_fielding_team`) to detect starters, then drops it before returning.
Bullpen aggregation needs to group relievers by `(game_pk, team)`, so this column must be
persisted.

- DDL: add `team VARCHAR` to `PITCHER_GAME_DDL` (`src/bblmlp/storage/warehouse.py`) — purely
  additive, no other column changes.
- `rollups.py::pitcher_game_stats`: keep `fld_team` through to the returned frame, renamed `team`
  for consistency with `team_game_stats.team` (same Statcast-abbreviation convention).
- Backward compatible: every existing `SELECT * FROM pitcher_game_stats` consumer (e.g.
  `build_features_cmd`) already selects columns by name where it matters, so the new column is
  additive-safe.
- **Rebuild required:** existing backfilled seasons (2021–2025) need `bblmlp build rollups
  --season <year>` rerun per season to populate the new column. This reads already-ingested
  `statcast_pitches` — no network refetch. Per CLAUDE.md's schema-change convention, delete the
  local `data/warehouse.duckdb` first (or let this rebuild happen as an explicit rollout step
  after merge — see §7).

## 3. New persisted rollup — `bullpen_game_stats`

New function in `rollups.py`, **taking `pitcher_game_stats` as input, not raw pitches** — a
deliberate deviation from #4's other rollup functions (which all take `statcast_pitches`
directly). Reusing the already-computed `is_starter` flag avoids re-deriving starter detection
logic a second time and keeps the two functions' notions of "starter" identical by construction.

```python
def bullpen_game_stats(pitcher_game_stats: pd.DataFrame) -> pd.DataFrame: ...
```

One row per `(game_pk, team)`. Filters `is_starter == False`, groups by `(game_pk, season, team)`:

| column | formula | notes |
|---|---|---|
| `pitches`, `batters_faced`, `k`, `bb`, `whiffs` | `sum(...)` over relievers | exact — these are raw counts already in `pitcher_game_stats` |
| `swstr_pct` | `whiffs / pitches` | mirrors how `pitcher_game_stats` itself derives this column |
| `avg_velo` | `sum(avg_velo · pitches) / sum(pitches)` | pitch-weighted mean — **documented approximation**, same pattern as #4's `xwoba` (each pitcher's `avg_velo` is itself already a per-pitcher mean, not a raw pitch-level value, so this is a weighted mean of means, not an exact pitch-level reconstruction) |
| `n_pitchers` | `count(distinct pitcher)` | raw (non-windowed) bullpen-usage signal — how many relievers a team used that game |

DDL: new `BULLPEN_GAME_DDL` in `warehouse.py`, wired into `init_schema`.

CLI: `bblmlp build rollups --season <year>` (`src/bblmlp/cli.py::build_rollups`) gains a third
write, right after `pitcher_game_stats`, in the same command — it already has the
`pitcher_game_stats` DataFrame in memory before writing, so `bullpen_game_stats` is computed from
that in-memory frame (not re-read from the warehouse).

## 4. New windowed output — `bullpen_features`

New module `src/bblmlp/features/bullpen.py`, following `rolling.py::pitcher_rolling_features`
almost exactly, with one structural difference: **partitioned by `team`, not `pitcher`** — a
team's bullpen as a rotating cast, not one individual's identity. Windows: **10, 35, 75** games
(same sizes as pitcher grain, per the roadmap's reasoning that bullpen usage drifts faster than a
single starter's form).

```python
def bullpen_rolling_features(
    con: duckdb.DuckDBPyConnection,
    bullpen_game_stats: pd.DataFrame,
    games: pd.DataFrame,
) -> pd.DataFrame: ...
```

One row per `(game_pk, team)`:

| column | formula |
|---|---|
| `k_pct_10/35/75` | `sum(k) / sum(batters_faced)` over the window |
| `bb_pct_10/35/75` | `sum(bb) / sum(batters_faced)` over the window |
| `swstr_pct_10/35/75` | `sum(whiffs) / sum(pitches)` over the window |
| `avg_velo_10/35/75` | trailing `AVG(avg_velo)` over the window (plain mean of already-weighted per-game values, same as pitcher grain) |
| `n_games_10/35/75` | `count(*)` over the window — prior bullpen-games actually present |

Ordering key: identical to #4 — join to `games` on `game_pk`, order by
`(game_date, game_datetime, game_pk)`.

CLI: `bblmlp build features --season <year>` (`build_features_cmd`) gains a third write for
`bullpen_features`, loading `bullpen_game_stats WHERE season <= <year>` (same cross-season
history-loading fix as #4, so a 75-game trailing window can span a season boundary), then filtering
the output back down to the target season before `replace_partition`.

## 5. Cold start

Not handled here, identical to #4: `ROWS BETWEEN N PRECEDING AND 1 PRECEDING` yields fewer rows
early and `NULL` only with zero prior bullpen-games on record. `n_games_w` exists so #6 can detect
partial windows without re-deriving it.

## 6. Testing

Mirrors #4's test suite structure (`tests/test_rollups.py`, `tests/test_features_rolling.py` or a
new `tests/test_features_bullpen.py`), no network, fixture-injected:

- **Team-column test:** `pitcher_game_stats` output includes a `team` column matching
  `team_game_stats.team` for the same game (same Statcast abbreviation for the fielding side).
- **Starter-exclusion test:** a fixture game with 1 starter + 2 relievers on a team produces a
  `bullpen_game_stats` row whose `pitches`/`k`/`bb`/`whiffs` sum only the two relievers — the
  starter's own stats must not leak in.
- **`n_pitchers` test:** counts distinct relievers, not total appearances.
- **`avg_velo` reconstruction test:** confirms the pitch-weighted formula against a hand-computed
  expected value on fixture data (same pattern as #4's `xwoba` test).
- **Leakage test (the correctness crux):** perturb game N's own bullpen stats, assert game N's own
  `bullpen_features` row is unchanged — only later games move.
- **Doubleheader ordering test:** two games same `game_date`, distinct `game_datetime`/`game_pk`,
  same team; later game's window includes the earlier one and not vice versa.
- **Partial-window test:** a team's first bullpen-game on record has `n_games_w = 0` and `NULL`
  rates; the second has `n_games_w = 1` matching game one's own rate.

## 7. Rollout (post-merge, not part of the test suite)

After merge, existing backfilled seasons need two rebuild passes to populate the new
table/columns — this is a data operation, not something the automated tests perform:

```bash
for season in 2021 2022 2023 2024 2025; do
  bb build rollups --season $season
  bb build features --season $season
done
```

## 8. Done when

- `pitcher_game_stats` has a `team` column; `bullpen_game_stats` and `bullpen_features` tables
  exist, populated via `bblmlp build rollups` / `bblmlp build features`.
- Bullpen aggregation is exact (summed raw counts from `is_starter == False` rows), never
  starter-subtracted from team totals.
- Window computation uses DuckDB SQL window functions, partitioned by `team`, at 10/35/75.
- Starter-exclusion test and leakage test both pass.
- `avg_velo`'s weighted-mean approximation is documented in code and covered by a reconstruction
  test, not silently treated as exact.
- All new tests pass under `uv run --no-sync pytest -q`; existing suite (110 tests as of this
  spec) stays green.
