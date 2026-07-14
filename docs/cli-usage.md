# CLI usage

Everything currently runnable through the `bblmlp` command, with real examples. This
covers the data-ingestion layer only — there is no model, no bet sizing, and no bet slip
yet (see `CLAUDE.md` for what's next).

## Setup

```bash
uv sync    # install dependencies into .venv
```

Alias the CLI — this form calls the module directly and never depends on `uv run`'s
editable-install shim:

```bash
alias bb='PYTHONPATH=src .venv/bin/python -m bblmlp.cli'
```

Everything below assumes `bb` is defined. Confirm it resolves:

```bash
bb --help
```

**Why not `uv run bblmlp` directly?** A macOS quirk keeps re-flagging the venv's `.pth`
file as hidden, which CPython then silently skips, breaking `import bblmlp` with
`ModuleNotFoundError`. It can recur mid-session, which is why `bb` bypasses it entirely
rather than re-running `chflags nohidden .venv/lib/python3.11/site-packages/*.pth`
before every command.

**DuckDB is single-writer.** If a command fails with `IOException: Could not set lock on
file`, another process (e.g. a DB-preview tab in an editor) has `data/warehouse.duckdb`
open — close it before retrying.

```bash
bb version    # sanity check
bb init-db    # create the warehouse + tables (idempotent, safe to re-run)
```

## Ingest — pull data into the warehouse

All ingest commands are idempotent: re-running them re-writes matching rows in place
(`INSERT OR REPLACE` keyed on the source's natural id — `game_pk` for games) rather than
duplicating.

### `ingest mlb` — schedule and game results (StatsAPI)

```bash
bb ingest mlb --live               # today's schedule
bb ingest mlb --date 2025-07-04    # one specific date
bb ingest mlb --backfill           # every season in config/settings.yaml
```
`home_win` is only populated for decided games (`Final` / `Completed Early`); in-progress
or tied games get `NULL`.

### `ingest statcast` — pitch-level Statcast backfill

```bash
bb ingest statcast --season 2024
```
Writes to `statcast_pitches`. This is the slow one — a full season is ~750k rows.

### `ingest fangraphs` — team/player season leaderboards

```bash
bb ingest fangraphs --season 2024
```
Writes `team_batting_season`, `team_pitching_season`, `batter_stats_season`,
`pitcher_stats_season`. Note: each table's schema locks to whatever columns the *first*
ingested season has — if a later season's FanGraphs columns differ, watch for silently
dropped columns.

### `ingest standings` — division standings

```bash
bb ingest standings --season 2024
```

### `ingest players` — Chadwick player-id crosswalk

```bash
bb ingest players
```
Refreshes `player_ids` (cross-references MLBAM/Statcast/FanGraphs/BBRef ids per player).

### `ingest live` — today's lineups/probables

```bash
bb ingest live                       # defaults to today
bb ingest live --date 2025-07-04
```
Writes `live_lineups`. Returns 0 rows on days with no games (e.g. All-Star break, offseason).

### `ingest all` — orchestrates every source above in dependency order

```bash
bb ingest all --date 2025-07-04   # players -> that day's schedule
bb ingest all --backfill          # full pipeline, every configured season
```

## Build — derived tables computed from what's already ingested

### `build team-crosswalk` — reconcile team ids across sources

```bash
bb build team-crosswalk --season 2024
```
Writes `team_crosswalk`: one row per `(team_id, season)` mapping StatsAPI's numeric
`team_id` to Statcast's and FanGraphs' differing abbreviations. Required before joining
`statcast_pitches` or FanGraphs tables against `games`/`standings`.

### `build rollups` — pitcher/team game stats from Statcast

```bash
bb build rollups --season 2024
```
Writes `pitcher_game_stats` / `team_game_stats`, computed from `statcast_pitches` already
in the warehouse (no network call).

### `build park-reference` — static park attributes

```bash
bb build park-reference
```
Writes `park_reference` from the distinct `games.venue` values seen across all ingested
history (no `--season` flag — it needs the full history to catch every venue name a
team has played under). Prints `Wrote N park_reference rows`.

## Check — repeatable data-quality guards

### `check venues` — stadium rename/relocation guard

```bash
bb check venues
```
Silent + exit code `0` means every `games.venue` string is already mapped in
`park_reference`. If a venue gets renamed (sponsor deal) or a team relocates, the new
string prints (one per line) and the command exits `1` — that's the signal to add it to
`park_reference` and re-run `build park-reference`.

## Kalshi market ingest — on a separate branch, not yet on `main`

The Kalshi client (public REST reads, no auth) is fully built and tested but lives on
branch `feat/kalshi-snapshot-ingest` (checked out at
`.worktrees/feat-kalshi-snapshot-ingest/`), not merged to `main` yet.

```bash
cd .worktrees/feat-kalshi-snapshot-ingest
bb ingest kalshi
```
(`bb` still resolves here — it's a relative-path alias, so it works from any directory
that has its own `src/` and `.venv/`, which this worktree does.)
Pulls every currently-open `KXMLBGAME-*` market from Kalshi, matches each to a `game_pk`
via `games` (regular-season games only — markets for exhibitions like the All-Star Game
won't match and get `game_pk = NULL`), and:
- appends one row per market side to `kalshi_quotes` (bid/ask, spread, volume, open
  interest, full order-book depth as JSON)
- writes a timestamped snapshot to `data/kalshi_snapshots/<UTC-timestamp>.parquet`

That worktree has its own copy of `data/warehouse.duckdb` (copied from `main`'s at setup
time) — it does **not** share `main`'s warehouse live, so schedule data ingested on
`main` afterward won't show up there until copied again.

## Peeking at the warehouse directly

```bash
PYTHONPATH=src .venv/bin/python scripts/peek.py
```
Read-only tour: row counts for every table, plus a few sample queries (games by month,
home-field win rate, strikeout leaders, pitch-type mix, team wRC+). Good first command
to run after any ingest to sanity-check it landed.
