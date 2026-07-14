# AGENTS.md

BBLMLP — local Python pipeline: ingest MLB/Kalshi data → build as-of features → predict game winners
→ compare to Kalshi markets → daily paper bet slip. Single DuckDB warehouse, single `bblmlp` Typer CLI.

## Setup

```bash
uv sync                                      # install deps into .venv
alias bb='PYTHONPATH=src .venv/bin/python -m bblmlp.cli'
```

All CLI examples below use `bb`. The alias calls the module directly and never depends on `uv run`'s
editable-install shim — bypassing the `.pth`/`UF_HIDDEN` gotcha entirely (see below).

## Gotchas

**Test-running:** always `uv run --no-sync pytest`, never bare `pytest`. The venv's editable
`.pth` gets `UF_HIDDEN` on macOS → CPython silently skips it → `import bblmlp` fails.
`pyproject.toml` sets `pythonpath = ["src"]` so pytest resolves directly; `--no-sync` prevents uv from
re-triggering the flag. If imports still fail, the `.pth` is the first suspect.

**DuckDB is single-writer.** If a command fails with `IOException: Could not set lock on file`,
another process (editor, DB browser) has `data/warehouse.duckdb` open — close it first.

**Schema change → warehouse rebuild:** DDL is `CREATE TABLE IF NOT EXISTS`, so old `.duckdb` files
won't pick up new columns. Delete `data/warehouse.duckdb` and re-ingest. For a purely additive column,
`ALTER TABLE` is a lighter alternative.

## Domain rules you'd otherwise guess wrong

- **Idempotency:** keyed on `game_pk` (`INSERT OR REPLACE` in a transaction). Re-running never
  duplicates rows.
- **`game_date` is authoritative,** not `game_datetime` (UTC, stored tz-naive). Join/partition on
  `game_date`.
- **Win label:** `home_win` is set only for decided games (`"Final"`, `"Completed Early"`).
  `"Completed Early"` (rain-shortened official) counts. Ties/undecided games get `NULL`.
- **No data leakage.** All features must be point-in-time (known before first pitch). Model validation
  is walk-forward by date only — never random shuffle.
- **Cross-source team joins go through `team_crosswalk`.** StatsAPI uses numeric `team_id`; Statcast
  uses abbreviations (`SF`); FanGraphs uses its own (`SFG`, `SDP`, `TBR`, `WSN`).
  `team_crosswalk` maps `(team_id, season)` to both. Never join raw abbreviations directly.
- **FanGraphs tables lock schema to the first season ingested** (`CREATE TABLE ... AS SELECT * FROM df
  LIMIT 0`). If a later season adds/renames columns, they silently don't exist.
- **FanGraphs fetches use `curl_cffi`** Chrome impersonation, not `requests` — FanGraphs 403s behind
  Cloudflare. The ~500-column JSON response gets deduped post-snake_case (`_dedupe`).

## Architecture

**DuckDB is the spine** — `src/bblmlp/storage/warehouse.py` owns the connection, DDL, and
idempotent writes. Every service reads/writes the same local file. No server.

**Ingest = fetch → normalize → upsert, split for testability.** Each source has a network client
and a pure normalizer (no network, takes dicts/DataFrames). Tests inject fixtures into normalizers.

**`ingest_all` takes a `fetchers` dict** keyed by source name (`chadwick`, `schedule`, `statcast`,
`fangraphs`, `standings`, `team_crosswalk`, `rollups`). A source runs only if its key is present.
`team_crosswalk` and `rollups` are derived (values are presence flags, not callables). Sources run in
dependency order: players → games → statcast → fangraphs → standings → team_crosswalk → rollups.

## What's built vs not

Built (on `main`, 57 tests): warehouse DDL, all MLB ingest sources (schedule, statcast, fangraphs,
standings, live, players, team_crosswalk), Statcast-derived pitcher/team/bullpen rollups, and
rolling-window team/pitcher/bullpen features. Backfill seasons 2021–2025.

Not yet built: rest of features (batter/lineup, cold-start/shrinkage), game-winner model
(`models/game/`), bet crafter (`betting/`), backtest (`backtest/`), player props (Phase 2).

## Workflow

Designs in `docs/superpowers/specs/`, plans in `docs/superpowers/plans/`. Backlog in
`docs/roadmap/`. Work on feature branches, TDD. Check `docs/superpowers/` for existing spec/plan
before writing code.

`scratch/winmodel/` is a throwaway sandbox (own venv) — not shipped, meant to be promoted into
`models/game/`. `scripts/peek.py` gives a read-only warehouse tour for sanity checks.
