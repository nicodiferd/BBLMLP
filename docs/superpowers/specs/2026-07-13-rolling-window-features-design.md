# As-Of Rolling-Window Feature Builder (team + pitcher grain)

> Design doc · 2026-07-13 · Status: **approved, ready for planning**
> Roadmap issue #4 (`docs/roadmap/2026-07-11-research-backlog.md`, Step 2 — `features/`).
> First `features/` module; foundational machinery that #5 (bullpen), #6 (cold-start), and #7
> (batter/lineup) build on top of.

## 1. Goal

Build the first module in `src/bblmlp/features/`: trailing, as-of-safe rolling-window stats over
the existing per-game rollup tables (`team_game_stats`, `pitcher_game_stats`), computed with
DuckDB window functions so every feature for game N is provably built only from games strictly
before N — never game N itself.

This is the single biggest lift in the research series this roadmap is based on (bullpen features
were its largest jump, and bullpen features need this machinery first). Everything downstream —
bullpen features (#5), cold-start/shrinkage (#6), lineup features (#7), and the game-winner model
itself (#8) — depends on this module existing.

**Out of scope for this spec:**
- Bullpen-game aggregation (#5) — a new fact table, not built here.
- Cold-start / shrinkage priors (#6) — partial windows are left as DuckDB naturally computes them
  (fewer rows early, `NULL` only with zero prior games); no priors are injected here.
- Batter/lineup features (#7) — blocked on the separate `#2` lineup spike, unrelated to this work.
- Any change to `rollups.py`'s existing schema (see §4 on the `xwoba` approximation below — the
  fix for that lives in a documented fast-follow, not here).

## 2. Approach

Two concrete, hand-written SQL builders — one per grain — rather than one generic
"numerator/denominator" engine. The two grains are already structurally different in what the
rollup tables persist (see §4), so a shared abstraction would be built from a single data point of
fit. Both builders share only the common window-function scaffolding
(`OVER (PARTITION BY … ORDER BY … ROWS BETWEEN N PRECEDING AND 1 PRECEDING)`); if #5/#7 later
reveal real duplication across three or four grains, that's the point to extract a shared helper —
not now.

## 3. Module layout

New package: `src/bblmlp/features/` (sibling to `ingest/` and `storage/`).
- `src/bblmlp/features/__init__.py`
- `src/bblmlp/features/rolling.py` — the two builder functions below.

Follows the existing "pure function over a DataFrame, no network, tests inject fixtures" pattern
used by `rollups.py`, except the transform itself runs as DuckDB SQL (registering the input
DataFrame against a connection and querying it) rather than pandas group-apply, per the roadmap's
explicit requirement to use DuckDB window functions, not Python loops.

```python
def team_rolling_features(con: duckdb.DuckDBPyConnection, team_game_stats: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame: ...
def pitcher_rolling_features(con: duckdb.DuckDBPyConnection, pitcher_game_stats: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame: ...
```

`games` is passed in narrowly (just `game_pk`, `game_date`, `game_datetime`) so the builders can
resolve the ordering key without a wider join than necessary.

## 4. Ordering key

Neither rollup table stores `game_date`, so both builders join to `games` on `game_pk`. The
`games` DDL has no doubleheader column, so the order key is:

```sql
ORDER BY game_date, game_datetime, game_pk
```

`game_datetime`'s UTC-vs-local slop (CLAUDE.md's existing warning) only affects *day* bucketing
across a UTC midnight boundary — it doesn't affect the relative order of two games recorded on the
same `game_date`, so it safely disambiguates doubleheaders. `game_pk` is the final deterministic
tiebreaker for same-timestamp edge cases.

## 5. Team-grain output — `team_features`

One row per `(game_pk, team)`. Windows: **30, 162** games.

`team_game_stats` only persists `pa`, `xwoba`, `k_pct`, `bb_pct` — no raw counts. Columns:

| column | formula | notes |
|---|---|---|
| `k_pct_30`, `k_pct_162` | `sum(k_pct·pa) / sum(pa)` over the window | algebraically exact vs. true `sum(k)/sum(pa)` — no `rollups.py` change needed |
| `bb_pct_30`, `bb_pct_162` | `sum(bb_pct·pa) / sum(pa)` over the window | same reconstruction |
| `xwoba_30`, `xwoba_162` | `sum(xwoba·pa) / sum(pa)` over the window | **documented approximation** — see below |
| `n_games_30`, `n_games_162` | `count(*)` over the window | prior games actually present; feeds #6's cold-start detection |

**`xwoba` approximation, stated explicitly:** `xwoba` in `team_game_stats` is already a per-game
mean over batted-ball events (via pandas `.mean()`), not a count-based rate — the rollup table
doesn't retain a batted-ball count, only `pa`. PA-weighting (`sum(xwoba·pa)/sum(pa)`) is a
reasonable proxy but is **not** exactly equal to the true `sum(batted-ball xwoba)/count(batted
balls)` the way the `k_pct`/`bb_pct` reconstructions are exact. Fast-follow (out of scope here):
persist a batted-ball count alongside `xwoba` in `rollups.py::team_game_stats` so this can become
an exact reconstruction.

## 6. Pitcher-grain output — `pitcher_features`

One row per `(game_pk, pitcher)`. Windows: **10, 35, 75** games.

`pitcher_game_stats` already persists raw counts (`k`, `bb`, `whiffs`, `pitches`,
`batters_faced`), so no reconstruction is needed — direct `sum(numerator)/sum(denominator)`:

| column | formula |
|---|---|
| `k_pct_10/35/75` | `sum(k) / sum(batters_faced)` over the window |
| `bb_pct_10/35/75` | `sum(bb) / sum(batters_faced)` over the window |
| `swstr_pct_10/35/75` | `sum(whiffs) / sum(pitches)` over the window |
| `avg_velo_10/35/75` | plain trailing mean of `avg_velo` (already a physical per-pitch measurement — no rate-reconstruction issue) |
| `n_games_10/35/75` | `count(*)` over the window |

`is_starter` is carried through unmodified (not windowed) so callers can filter starter vs.
reliever rows. Full bullpen-game aggregation (grouping relievers by team+game) is #5's job, not
this module's — this builder just windows whatever per-pitcher-per-game rows it's given.

## 7. Cold start (explicitly deferred)

Not handled here. `ROWS BETWEEN N PRECEDING AND 1 PRECEDING` naturally yields fewer rows early in
a team's/pitcher's history and DuckDB returns partial-window aggregates as-is; the result is
`NULL` only when zero prior games exist (a team's/pitcher's literal first game on record).
Shrinkage toward a prior, or any other cold-start policy, is #6 — not touched here. The
`n_games_w` columns exist specifically so #6 has what it needs to detect a partial window without
re-deriving it.

## 8. FanGraphs exclusion

Confirmed out of scope, per the roadmap and the ingest design doc §3.3: FanGraphs season tables
are prior-season context only, never a rolling source.

## 9. Testing

- **Leakage test (the correctness crux):** build a small in-memory DuckDB connection + fixture
  rollup rows for one team/pitcher across several consecutive games. Perturb game N's own stat
  value (e.g. double its `k_pct`) and assert game N's own feature row is unchanged — only games
  N+1, N+2, … move. The guard is the `1 PRECEDING` upper bound itself; the test proves it, it
  doesn't add a separate check.
- **Doubleheader ordering test:** fixture two games on the same `game_date` for one team, distinct
  `game_datetime`/`game_pk`; assert the later game's window includes the earlier game and not
  vice versa.
- **Partial-window test:** a team's/pitcher's first game in the fixture has `n_games_w = 0` and a
  `NULL` rate; the second has `n_games_w = 1` and a rate equal to game one's own rate.
- **`xwoba` reconstruction test:** confirms the PA-weighted formula against a hand-computed
  expected value on fixture data (documents the approximation numerically, not just in prose).
- Follows existing fixture-injection conventions (`tests/test_rollups.py`) — no network, no real
  warehouse file required.

## 10. CLI

`bblmlp build features --season <year>`, added to the existing `build_app` in `cli.py`, following
the exact `build_rollups`/`build_park_reference` pattern:

```python
@build_app.command("features")
def build_features_cmd(season: int = typer.Option(..., "--season")) -> None:
    """Compute as-of rolling-window features (team + pitcher grain) for a season."""
    ...
    team_rows = replace_partition(con, "team_features", team_rolling_features(con, team_game_stats, games), "season")
    pitcher_rows = replace_partition(con, "pitcher_features", pitcher_rolling_features(con, pitcher_game_stats, games), "season")
```

Season-partitioned via `replace_partition`, same idempotency guarantee as `build rollups` —
re-running for a season replaces only that season's rows.

## 11. Done when

- `team_features` and `pitcher_features` tables exist, populated via `bblmlp build features
  --season <year>`, matching the column sets in §5/§6.
- Window computation uses DuckDB SQL window functions, not pandas `.rolling()` or Python loops.
- Ordering key is `(game_date, game_datetime, game_pk)`, validated by a doubleheader test.
- Leakage test passes: perturbing game N's stats never changes game N's own feature row.
- `xwoba`'s PA-weighted approximation is documented in code (docstring) and covered by a
  reconstruction test, not silently treated as exact.
- All new tests pass under `uv run --no-sync pytest -q`; existing suite (72 tests as of this spec)
  stays green.
