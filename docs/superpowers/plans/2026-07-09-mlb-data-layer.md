# MLB Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the MLB data ingest into a comprehensive, model-ready warehouse — full Statcast, a player-id crosswalk, FanGraphs season tables, standings, Statcast-derived game rollups (with starters/lineups), and a live daily lineup pull.

**Architecture:** Extend `src/bblmlp/ingest/mlb/` following the existing fetch→normalize→write seam: thin network `fetch_*` functions (never unit-tested) feed **pure normalizers** (unit-tested with fixtures) whose output goes to **idempotent, partition-replacing writers** in `storage/warehouse.py`. Ingest lands raw facts at their natural grain; rolling/as-of features are a later service and are explicitly out of scope here.

**Tech Stack:** Python 3.11+, uv, DuckDB, pandas, `MLB-StatsAPI`, `pybaseball`, Typer, pytest.

## Global Constraints

- Python floor: `requires-python = ">=3.11"`.
- Run tests with `uv run --no-sync pytest` (never bare `pytest` — the venv `.pth` gets macOS `UF_HIDDEN` and CPython skips it; `pyproject.toml` sets `pythonpath = ["src"]`).
- Warehouse path comes from `config/settings.yaml` → `data.warehouse_path` (`data/warehouse.duckdb`); backfill seasons from `data.backfill_seasons` = `[2021, 2022, 2023, 2024, 2025]`.
- Every writer is idempotent: re-ingesting a partition (season, or date for live) replaces those rows, never appends duplicates. Wrap multi-statement writes in `BEGIN TRANSACTION` / `COMMIT` with `ROLLBACK` on exception.
- Pure normalizers must not touch the network and must not mutate their input DataFrame (`df = df.copy()` first).
- Ingest lands raw facts only — no rolling windows, no "as-of" alignment, no leakage-sensitive computation (that is Service 2).
- New dependency needed: `pybaseball` already in `pyproject.toml`; no new deps expected. If FanGraphs helpers require it, add nothing without noting it.
- Commit after every task with a `feat:`/`refactor:` message; end messages with the repo's `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer.

## File Structure

- `src/bblmlp/storage/warehouse.py` — add DDL constants for every new table; add generic `replace_partition()` and `replace_all()` writers; register all DDL in `init_schema()`.
- `src/bblmlp/ingest/mlb/statcast.py` — widen the kept column set + DDL (modify).
- `src/bblmlp/ingest/mlb/players.py` — Chadwick crosswalk fetch/normalize + `resolve_player_id()` (create).
- `src/bblmlp/ingest/mlb/schedule.py` — add probable-pitcher-id enrichment hook (modify).
- `src/bblmlp/ingest/mlb/fangraphs.py` — four season tables (create).
- `src/bblmlp/ingest/mlb/standings.py` — standings (create).
- `src/bblmlp/ingest/mlb/rollups.py` — pure derivations over `statcast_pitches` (create).
- `src/bblmlp/ingest/mlb/live.py` — today's probables + lineups (create).
- `src/bblmlp/ingest/mlb/ingest.py` — `ingest_all` orchestrator (modify).
- `src/bblmlp/cli.py` — new `ingest`/`build` subcommands (modify).
- `tests/` — one test module per source, plus fixtures under `tests/fixtures/`.

---

### Task 1: Generic idempotent writers

**Files:**
- Modify: `src/bblmlp/storage/warehouse.py`
- Modify: `src/bblmlp/storage/__init__.py`
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Produces: `replace_partition(con, table: str, df: pd.DataFrame, part_col: str) -> int` — deletes all rows whose `part_col` value appears in `df`, then inserts `df`. `replace_all(con, table: str, df: pd.DataFrame) -> int` — truncate + insert. Both transactional, both no-op on empty `df`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_warehouse.py (add)
import duckdb
from bblmlp.storage import replace_partition, replace_all

def _mk(con):
    con.execute("CREATE TABLE t (season INTEGER, v INTEGER)")

def test_replace_partition_is_idempotent():
    con = duckdb.connect(":memory:")
    _mk(con)
    import pandas as pd
    df = pd.DataFrame({"season": [2024, 2024], "v": [1, 2]})
    assert replace_partition(con, "t", df, "season") == 2
    assert replace_partition(con, "t", df, "season") == 2  # rerun
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 2  # no dupes
    assert con.execute("SELECT count(*) FROM t WHERE season=2023").fetchone()[0] == 0

def test_replace_partition_leaves_other_partitions():
    con = duckdb.connect(":memory:")
    _mk(con)
    import pandas as pd
    replace_partition(con, "t", pd.DataFrame({"season":[2023],"v":[9]}), "season")
    replace_partition(con, "t", pd.DataFrame({"season":[2024],"v":[1]}), "season")
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 2

def test_replace_all_truncates():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE p (id INTEGER)")
    import pandas as pd
    replace_all(con, "p", pd.DataFrame({"id":[1,2,3]}))
    replace_all(con, "p", pd.DataFrame({"id":[9]}))
    assert con.execute("SELECT count(*) FROM p").fetchone()[0] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_warehouse.py -k "replace" -v`
Expected: FAIL — `ImportError: cannot import name 'replace_partition'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/bblmlp/storage/warehouse.py (add)
def replace_partition(con, table: str, df, part_col: str) -> int:
    if df is None or len(df) == 0:
        return 0
    parts = list(dict.fromkeys(df[part_col].tolist()))
    cols = ", ".join(df.columns)
    con.register("_df_repl", df)
    try:
        con.execute("BEGIN TRANSACTION")
        try:
            ph = ", ".join(["?"] * len(parts))
            con.execute(f"DELETE FROM {table} WHERE {part_col} IN ({ph})", parts)
            con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _df_repl")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.unregister("_df_repl")
    return len(df)

def replace_all(con, table: str, df) -> int:
    if df is None or len(df) == 0:
        return 0
    cols = ", ".join(df.columns)
    con.register("_df_all", df)
    try:
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(f"DELETE FROM {table}")
            con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _df_all")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.unregister("_df_all")
    return len(df)
```
Then export both from `src/bblmlp/storage/__init__.py` (add to the import list and `__all__`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_warehouse.py -k "replace" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/storage/warehouse.py src/bblmlp/storage/__init__.py tests/test_warehouse.py
git commit -m "feat: generic idempotent replace_partition/replace_all writers"
```

---

### Task 2: Widen `statcast_pitches` to the comprehensive schema

**Files:**
- Modify: `src/bblmlp/storage/warehouse.py` (STATCAST_DDL)
- Modify: `src/bblmlp/ingest/mlb/statcast.py`
- Test: `tests/test_statcast.py`, `tests/fixtures/statcast_sample.csv`

**Interfaces:**
- Consumes: `replace_partition` (Task 1).
- Produces: widened `normalize_statcast(df, season) -> pd.DataFrame` keeping the full `STATCAST_COLUMNS`; `write_statcast(con, df)` now delegates to `replace_partition(con, "statcast_pitches", df, "season")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_statcast.py (add)
import pandas as pd
from bblmlp.ingest.mlb.statcast import normalize_statcast

def test_normalize_keeps_handedness_count_and_value_columns():
    raw = pd.DataFrame({
        "game_pk": [1], "game_date": ["2024-04-01"], "pitcher": [111], "batter": [222],
        "events": ["strikeout"], "description": ["swinging_strike"], "pitch_type": ["FF"],
        "release_speed": [95.1], "estimated_woba_using_speedangle": [0.20],
        "at_bat_number": [1], "pitch_number": [3],
        "stand": ["R"], "p_throws": ["L"], "balls": [1], "strikes": [2],
        "launch_speed": [88.0], "launch_angle": [12.0], "woba_value": [0.0],
        "delta_run_exp": [-0.1], "inning": [1], "inning_topbot": ["Top"],
        "home_team": ["SF"], "away_team": ["COL"],
    })
    out = normalize_statcast(raw, season=2024)
    for col in ["stand", "p_throws", "balls", "strikes", "launch_speed",
                "delta_run_exp", "inning_topbot", "home_team", "season"]:
        assert col in out.columns
    assert out["season"].iloc[0] == 2024
    assert out["game_pk"].dtype == "int64"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_statcast.py -k handedness -v`
Expected: FAIL — assertion error, `stand` not in columns (current normalizer keeps only 12).

- [ ] **Step 3: Write minimal implementation**

```python
# src/bblmlp/ingest/mlb/statcast.py — replace STATCAST_COLUMNS with the comprehensive set
STATCAST_COLUMNS = [
    # identity & context
    "game_pk", "game_date", "season", "game_type", "home_team", "away_team",
    "inning", "inning_topbot", "at_bat_number", "pitch_number",
    "pitcher", "batter", "player_name", "p_throws", "stand",
    # pitch
    "pitch_type", "pitch_name", "release_speed", "effective_speed",
    "release_spin_rate", "spin_axis", "release_pos_x", "release_pos_z",
    "release_extension", "pfx_x", "pfx_z", "plate_x", "plate_z", "zone",
    "type", "description", "sz_top", "sz_bot",
    # count / state
    "balls", "strikes", "outs_when_up", "on_1b", "on_2b", "on_3b",
    # outcome
    "events", "bb_type", "hit_location", "launch_speed", "launch_angle",
    "hit_distance_sc", "launch_speed_angle",
    # value
    "estimated_woba_using_speedangle", "estimated_ba_using_speedangle",
    "woba_value", "woba_denom", "babip_value", "iso_value",
    "delta_run_exp", "delta_home_win_exp",
    # score state
    "bat_score", "fld_score", "home_score", "away_score",
]
```
Keep `normalize_statcast` logic the same (`df.copy()`, set `season`, drop null `game_pk`, `keep = [c for c in STATCAST_COLUMNS if c in df.columns]`, cast `game_pk` to int64). Change `write_statcast` body to:
```python
from bblmlp.storage import replace_partition
def write_statcast(con, df):
    return replace_partition(con, "statcast_pitches", df, "season")
```
Update `STATCAST_DDL` in `warehouse.py` to declare all columns above (types: ids/counts `BIGINT`/`INTEGER`, dates `DATE`, measures `DOUBLE`, text `VARCHAR`). Keep `game_pk BIGINT`, `season INTEGER`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_statcast.py -v`
Expected: PASS (existing + new). Existing idempotency test still green (write path unchanged behaviorally).

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/mlb/statcast.py src/bblmlp/storage/warehouse.py tests/test_statcast.py
git commit -m "feat: widen statcast_pitches to comprehensive schema"
```

> **Manual step (not a test), run once after this task:** delete the stale `data/warehouse.duckdb`, then `uv run bblmlp ingest statcast --season 2024` to re-backfill one season and eyeball the new columns land. Full backfill happens in Task 10.

---

### Task 3: Player-id crosswalk (`player_ids`)

**Files:**
- Create: `src/bblmlp/ingest/mlb/players.py`
- Modify: `src/bblmlp/storage/warehouse.py` (PLAYER_IDS_DDL + init_schema)
- Modify: `src/bblmlp/cli.py`
- Test: `tests/test_players.py`

**Interfaces:**
- Produces: `normalize_players(df) -> pd.DataFrame` (columns: `key_mlbam, key_fangraphs, key_bbref, key_retro, name_first, name_last, mlb_played_first, mlb_played_last`); `resolve_player_id(players_df, name_first, name_last, active_year=None) -> int | None`; `fetch_chadwick() -> pd.DataFrame` (thin, network).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_players.py
import pandas as pd
from bblmlp.ingest.mlb.players import normalize_players, resolve_player_id

def _people():
    return pd.DataFrame({
        "key_mlbam": [111, 222, 333],
        "key_fangraphs": [11, 22, 33],
        "key_bbref": ["a", "b", "c"], "key_retro": ["r1","r2","r3"],
        "name_first": ["Ryan", "Luis", "Luis"], "name_last": ["Feltner","Garcia","Garcia"],
        "mlb_played_first": [2021, 2010, 2022], "mlb_played_last": [2026, 2016, 2026],
    })

def test_normalize_players_selects_crosswalk_columns():
    out = normalize_players(_people())
    assert list(out.columns)[:2] == ["key_mlbam", "key_fangraphs"]
    assert out["key_mlbam"].dtype == "int64"

def test_resolve_unique_name():
    assert resolve_player_id(_people(), "Ryan", "Feltner") == 111

def test_resolve_ambiguous_name_uses_active_year():
    # two Luis Garcias; the 2024-active one is key_mlbam 333
    assert resolve_player_id(_people(), "Luis", "Garcia", active_year=2024) == 333

def test_resolve_unresolvable_returns_none():
    assert resolve_player_id(_people(), "Nobody", "Here") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_players.py -v`
Expected: FAIL — module `players` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# src/bblmlp/ingest/mlb/players.py
from __future__ import annotations
import pandas as pd

_COLS = ["key_mlbam", "key_fangraphs", "key_bbref", "key_retro",
         "name_first", "name_last", "mlb_played_first", "mlb_played_last"]

def normalize_players(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    out = df[[c for c in _COLS if c in df.columns]].copy()
    out = out[out["key_mlbam"].notna()]
    out["key_mlbam"] = out["key_mlbam"].astype("int64")
    return out

def resolve_player_id(players: pd.DataFrame, name_first: str, name_last: str,
                      active_year: int | None = None) -> int | None:
    m = players[(players["name_first"].str.casefold() == name_first.casefold())
                & (players["name_last"].str.casefold() == name_last.casefold())]
    if active_year is not None and len(m) > 1:
        m = m[(players["mlb_played_first"] <= active_year)
              & (players["mlb_played_last"] >= active_year)]
    if len(m) == 1:
        return int(m["key_mlbam"].iloc[0])
    return None

def fetch_chadwick() -> pd.DataFrame:
    from pybaseball import chadwick_register
    return chadwick_register()
```
Add `PLAYER_IDS_DDL` to `warehouse.py` (all `_COLS`; `key_mlbam BIGINT PRIMARY KEY`, other keys `BIGINT`/`VARCHAR`, names `VARCHAR`, years `INTEGER`) and register in `init_schema`. Add CLI:
```python
@ingest_app.command("players")
def ingest_players() -> None:
    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.players import fetch_chadwick, normalize_players
    from bblmlp.storage import connect, init_schema, replace_all
    s = load_settings(); con = connect(s.data.warehouse_path); init_schema(con)
    n = replace_all(con, "player_ids", normalize_players(fetch_chadwick()))
    con.close(); typer.echo(f"Loaded {n} players")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_players.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/mlb/players.py src/bblmlp/storage/warehouse.py src/bblmlp/cli.py tests/test_players.py
git commit -m "feat: Chadwick player-id crosswalk + resolver"
```

---

### Task 4: Enrich `games` with probable-pitcher ids

**Files:**
- Modify: `src/bblmlp/storage/warehouse.py` (add 2 columns to GAMES_DDL + `_GAME_COLUMNS`)
- Modify: `src/bblmlp/ingest/mlb/schedule.py`
- Test: `tests/test_schedule_normalizer.py`

**Interfaces:**
- Consumes: `resolve_player_id` (Task 3).
- Produces: `normalize_schedule(raw_games, season, players=None)` — when `players` (crosswalk df) is passed, populates `home_probable_pitcher_id` / `away_probable_pitcher_id` by resolving the probable-pitcher names; when `None`, leaves them null.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schedule_normalizer.py (add)
import pandas as pd
from bblmlp.ingest.mlb.schedule import normalize_schedule

def test_probable_pitcher_ids_resolved_when_players_supplied():
    players = pd.DataFrame({
        "key_mlbam": [111], "name_first": ["Ryan"], "name_last": ["Feltner"],
        "mlb_played_first": [2021], "mlb_played_last": [2026],
        "key_fangraphs":[1],"key_bbref":["x"],"key_retro":["y"],
    })
    raw = [{"game_id": 5, "game_date": "2024-05-01", "home_name": "SF",
            "away_name": "COL", "status": "Final", "home_score": 3, "away_score": 1,
            "home_probable_pitcher": "Ryan Feltner", "away_probable_pitcher": ""}]
    rows = normalize_schedule(raw, season=2024, players=players)
    assert rows[0]["home_probable_pitcher_id"] == 111
    assert rows[0]["away_probable_pitcher_id"] is None

def test_probable_pitcher_ids_null_without_players():
    raw = [{"game_id": 5, "game_date": "2024-05-01", "home_name": "SF",
            "away_name": "COL", "status": "Final", "home_score": 3, "away_score": 1,
            "home_probable_pitcher": "Ryan Feltner"}]
    rows = normalize_schedule(raw, season=2024)
    assert rows[0]["home_probable_pitcher_id"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_schedule_normalizer.py -k probable -v`
Expected: FAIL — `KeyError: 'home_probable_pitcher_id'`.

- [ ] **Step 3: Write minimal implementation**

Add a `players=None` parameter to `normalize_schedule`. Add a helper that splits a "First Last" string and calls `resolve_player_id`:
```python
def _resolve(players, full_name, season):
    if players is None or not full_name:
        return None
    parts = full_name.strip().split(" ", 1)
    if len(parts) != 2:
        return None
    from bblmlp.ingest.mlb.players import resolve_player_id
    return resolve_player_id(players, parts[0], parts[1], active_year=season)
```
In the row dict add:
```python
"home_probable_pitcher_id": _resolve(players, raw.get("home_probable_pitcher") or "", season),
"away_probable_pitcher_id": _resolve(players, raw.get("away_probable_pitcher") or "", season),
```
Add `home_probable_pitcher_id INTEGER`, `away_probable_pitcher_id INTEGER` to `GAMES_DDL` and to `_GAME_COLUMNS` in `warehouse.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_schedule_normalizer.py -v`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/mlb/schedule.py src/bblmlp/storage/warehouse.py tests/test_schedule_normalizer.py
git commit -m "feat: resolve probable-pitcher ids on games via crosswalk"
```

---

### Task 5: FanGraphs team season tables

**Files:**
- Create: `src/bblmlp/ingest/mlb/fangraphs.py`
- Modify: `src/bblmlp/storage/warehouse.py` (TEAM_BATTING_DDL, TEAM_PITCHING_DDL)
- Modify: `src/bblmlp/cli.py`
- Test: `tests/test_fangraphs.py`

**Interfaces:**
- Consumes: `replace_partition` (Task 1).
- Produces: `normalize_team_batting(df, season)` and `normalize_team_pitching(df, season)` → tidy frames with a `season` column and snake_cased stat columns; thin `fetch_team_batting(season)` / `fetch_team_pitching(season)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fangraphs.py
import pandas as pd
from bblmlp.ingest.mlb.fangraphs import normalize_team_batting, normalize_team_pitching

def test_team_batting_tidies_and_tags_season():
    raw = pd.DataFrame({"Team": ["SFG"], "wRC+": [105], "wOBA": [0.320], "HR": [180]})
    out = normalize_team_batting(raw, season=2024)
    assert out["season"].iloc[0] == 2024
    assert "wrc_plus" in out.columns and out["wrc_plus"].iloc[0] == 105
    assert "team" in out.columns

def test_team_pitching_tidies_and_tags_season():
    raw = pd.DataFrame({"Team": ["SFG"], "FIP": [3.9], "ERA": [3.8], "K/9": [9.1]})
    out = normalize_team_pitching(raw, season=2024)
    assert out["season"].iloc[0] == 2024
    assert "fip" in out.columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_fangraphs.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# src/bblmlp/ingest/mlb/fangraphs.py
from __future__ import annotations
import re
import pandas as pd

def _snake(name: str) -> str:
    name = name.replace("+", "_plus").replace("%", "_pct").replace("/", "_per_")
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    return name

def _tidy(df: pd.DataFrame, season: int) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_snake(c) for c in df.columns]
    df["season"] = season
    return df

def normalize_team_batting(df, season):  return _tidy(df, season)
def normalize_team_pitching(df, season): return _tidy(df, season)

def fetch_team_batting(season):
    from pybaseball import team_batting
    return team_batting(season)

def fetch_team_pitching(season):
    from pybaseball import team_pitching
    return team_pitching(season)
```
DDL note: FanGraphs frames are wide and vary year to year. Create the tables from the **first normalized frame** rather than a fixed column list — in `init_schema`, skip these; the writer creates them on demand. Add to `warehouse.py`:
```python
def ensure_table_from_df(con, table, df):
    con.register("_tmpl", df)
    con.execute(f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM _tmpl LIMIT 0")
    con.unregister("_tmpl")
```
CLI `ingest fangraphs --season` calls `ensure_table_from_df` then `replace_partition(..., "season")` for each of the four tables (team tables here; player tables in Task 6).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_fangraphs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/mlb/fangraphs.py src/bblmlp/storage/warehouse.py src/bblmlp/cli.py tests/test_fangraphs.py
git commit -m "feat: FanGraphs team batting/pitching season tables"
```

---

### Task 6: FanGraphs player season tables

**Files:**
- Modify: `src/bblmlp/ingest/mlb/fangraphs.py`
- Modify: `src/bblmlp/cli.py` (extend `ingest fangraphs`)
- Test: `tests/test_fangraphs.py`

**Interfaces:**
- Produces: `normalize_pitcher_stats(df, season)` and `normalize_batter_stats(df, season)` → tidy frames tagged with `season`, `key_fangraphs` preserved for the crosswalk join; thin `fetch_pitching_stats(season)` / `fetch_batting_stats(season)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fangraphs.py (add)
import pandas as pd
from bblmlp.ingest.mlb.fangraphs import normalize_pitcher_stats, normalize_batter_stats

def test_pitcher_stats_preserve_fangraphs_id_and_tag_season():
    raw = pd.DataFrame({"IDfg": [22], "Name": ["A B"], "K%": [0.30], "xFIP": [3.5]})
    out = normalize_pitcher_stats(raw, season=2024)
    assert out["season"].iloc[0] == 2024
    assert "key_fangraphs" in out.columns and out["key_fangraphs"].iloc[0] == 22
    assert "k_pct" in out.columns

def test_batter_stats_preserve_fangraphs_id():
    raw = pd.DataFrame({"IDfg": [11], "Name": ["C D"], "wRC+": [140], "ISO": [0.25]})
    out = normalize_batter_stats(raw, season=2024)
    assert out["key_fangraphs"].iloc[0] == 11
    assert "wrc_plus" in out.columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_fangraphs.py -k "stats" -v`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/bblmlp/ingest/mlb/fangraphs.py (add)
def _tidy_players(df, season):
    out = _tidy(df, season)  # snake_case + season
    if "idfg" in out.columns:
        out = out.rename(columns={"idfg": "key_fangraphs"})
    return out

def normalize_pitcher_stats(df, season): return _tidy_players(df, season)
def normalize_batter_stats(df, season):  return _tidy_players(df, season)

def fetch_pitching_stats(season):
    from pybaseball import pitching_stats
    return pitching_stats(season, season)

def fetch_batting_stats(season):
    from pybaseball import batting_stats
    return batting_stats(season, season)
```
Extend the `ingest fangraphs --season` command to also `ensure_table_from_df` + `replace_partition` the `pitcher_stats_season` and `batter_stats_season` tables.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_fangraphs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/mlb/fangraphs.py src/bblmlp/cli.py tests/test_fangraphs.py
git commit -m "feat: FanGraphs pitcher/batter season tables"
```

---

### Task 7: Standings

**Files:**
- Create: `src/bblmlp/ingest/mlb/standings.py`
- Modify: `src/bblmlp/storage/warehouse.py` (STANDINGS_DDL + init_schema)
- Modify: `src/bblmlp/cli.py`
- Test: `tests/test_standings.py`, `tests/fixtures/standings_sample.json`

**Interfaces:**
- Produces: `normalize_standings(raw, season) -> pd.DataFrame` (`season, team_id, team_name, w, l, win_pct, gb, div_rank, streak, runs_scored, runs_allowed`); thin `fetch_standings(season)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_standings.py
from bblmlp.ingest.mlb.standings import normalize_standings

def test_normalize_standings_flattens_divisions():
    raw = {  # shape of statsapi.standings_data(): {division_id: {"teams": [...]}}
        200: {"teams": [
            {"team_id": 137, "name": "SF", "w": 90, "l": 72, "gb": "-",
             "div_rank": "1", "streak": "W2"},
        ]},
    }
    rows = normalize_standings(raw, season=2024)
    assert rows.iloc[0]["team_id"] == 137
    assert rows.iloc[0]["w"] == 90
    assert rows.iloc[0]["season"] == 2024
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_standings.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# src/bblmlp/ingest/mlb/standings.py
from __future__ import annotations
import pandas as pd

def normalize_standings(raw: dict, season: int) -> pd.DataFrame:
    rows = []
    for _div_id, div in raw.items():
        for t in div.get("teams", []):
            rows.append({
                "season": season,
                "team_id": t.get("team_id"),
                "team_name": t.get("name"),
                "w": t.get("w"), "l": t.get("l"),
                "win_pct": float(t["w"]) / max(1, (t.get("w", 0) + t.get("l", 0))),
                "gb": str(t.get("gb")),
                "div_rank": t.get("div_rank"),
                "streak": t.get("streak"),
                "runs_scored": t.get("runs_scored"),
                "runs_allowed": t.get("runs_allowed"),
            })
    return pd.DataFrame(rows)

def fetch_standings(season: int):
    import statsapi
    return statsapi.standings_data(season=season)
```
Add `STANDINGS_DDL` (`season INTEGER, team_id INTEGER, team_name VARCHAR, w INTEGER, l INTEGER, win_pct DOUBLE, gb VARCHAR, div_rank VARCHAR, streak VARCHAR, runs_scored INTEGER, runs_allowed INTEGER`) + register in `init_schema`. CLI `ingest standings --season` → `replace_partition(con,"standings",df,"season")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_standings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/mlb/standings.py src/bblmlp/storage/warehouse.py src/bblmlp/cli.py tests/test_standings.py
git commit -m "feat: standings ingest"
```

---

### Task 8: Statcast-derived game rollups + starters/lineups

**Files:**
- Create: `src/bblmlp/ingest/mlb/rollups.py`
- Modify: `src/bblmlp/storage/warehouse.py` (PITCHER_GAME_DDL, TEAM_GAME_DDL)
- Modify: `src/bblmlp/cli.py` (`build rollups`)
- Test: `tests/test_rollups.py`

**Interfaces:**
- Consumes: widened `statcast_pitches` columns (Task 2), `replace_partition` (Task 1).
- Produces: `pitcher_game_stats(pitches_df) -> pd.DataFrame` (`game_pk, pitcher, season, pitches, batters_faced, k, bb, whiffs, csw_pct, xwoba_against, avg_velo, is_starter`); `team_game_stats(pitches_df) -> pd.DataFrame` (`game_pk, team, season, pa, xwoba, k_pct, bb_pct, runs`); `lineup(pitches_df) -> pd.DataFrame` (`game_pk, team, batter, batting_order`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rollups.py
import pandas as pd
from bblmlp.ingest.mlb.rollups import pitcher_game_stats, lineup

def _pitches():
    # one game: SF (home) bats bottom, COL (away) bats top.
    # COL pitcher 900 starts (first pitch of the game, top of 1st? no—home pitches in top1)
    return pd.DataFrame({
        "game_pk": [1,1,1,1],
        "season": [2024]*4,
        "inning": [1,1,1,2],
        "inning_topbot": ["Top","Top","Bot","Bot"],
        "home_team": ["SF"]*4, "away_team": ["COL"]*4,
        "pitcher": [500,500,900,900],     # SF pitcher 500 throws in Top1; COL 900 in Bot1
        "batter":  [10,11,20,21],
        "at_bat_number": [1,2,3,4],
        "pitch_number": [1,1,1,1],
        "events": ["strikeout","walk","single","field_out"],
        "description": ["swinging_strike","ball","hit_into_play","hit_into_play"],
        "estimated_woba_using_speedangle": [0.0,0.0,0.9,0.1],
        "release_speed": [95,96,93,92],
    })

def test_starter_is_first_pitcher_for_each_side():
    out = pitcher_game_stats(_pitches())
    starters = set(out[out["is_starter"]]["pitcher"])
    assert starters == {500, 900}

def test_lineup_orders_batters_by_first_appearance():
    lo = lineup(_pitches())
    col = lo[lo["team"] == "COL"].sort_values("batting_order")
    assert list(col["batter"]) == [10, 11]  # COL bats in the Top half
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_rollups.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# src/bblmlp/ingest/mlb/rollups.py
from __future__ import annotations
import pandas as pd

def _fielding_team(df: pd.DataFrame) -> pd.Series:
    # Top of inning: away bats, home pitches. Bottom: home bats, away pitches.
    return df["home_team"].where(df["inning_topbot"] == "Top", df["away_team"])

def _batting_team(df: pd.DataFrame) -> pd.Series:
    return df["away_team"].where(df["inning_topbot"] == "Top", df["home_team"])

def pitcher_game_stats(pitches: pd.DataFrame) -> pd.DataFrame:
    df = pitches.copy()
    df["fld_team"] = _fielding_team(df)
    g = df.groupby(["game_pk", "season", "pitcher"], as_index=False)
    out = g.agg(
        pitches=("pitch_number", "size"),
        batters_faced=("at_bat_number", "nunique"),
        avg_velo=("release_speed", "mean"),
        xwoba_against=("estimated_woba_using_speedangle", "mean"),
    )
    # k / bb from per-PA terminal events
    ev = df.dropna(subset=["events"])
    k = ev[ev["events"] == "strikeout"].groupby(["game_pk","pitcher"]).size()
    bb = ev[ev["events"] == "walk"].groupby(["game_pk","pitcher"]).size()
    whiff = df[df["description"] == "swinging_strike"].groupby(["game_pk","pitcher"]).size()
    out = out.set_index(["game_pk","pitcher"])
    out["k"] = k; out["bb"] = bb; out["whiffs"] = whiff
    out[["k","bb","whiffs"]] = out[["k","bb","whiffs"]].fillna(0).astype(int)
    out["csw_pct"] = out["whiffs"] / out["pitches"]
    out = out.reset_index()
    # starter = pitcher of the minimum at_bat_number faced by each fielding side
    first_ab = df.sort_values("at_bat_number").groupby(["game_pk","fld_team"]).first().reset_index()
    starters = set(zip(first_ab["game_pk"], first_ab["pitcher"]))
    out["is_starter"] = [(gp, p) in starters for gp, p in zip(out["game_pk"], out["pitcher"])]
    return out

def lineup(pitches: pd.DataFrame) -> pd.DataFrame:
    df = pitches.copy()
    df["team"] = _batting_team(df)
    first = df.sort_values("at_bat_number").groupby(["game_pk","team","batter"], as_index=False)["at_bat_number"].min()
    first = first.sort_values(["game_pk","team","at_bat_number"])
    first["batting_order"] = first.groupby(["game_pk","team"]).cumcount() + 1
    return first[["game_pk","team","batter","batting_order"]]

def team_game_stats(pitches: pd.DataFrame) -> pd.DataFrame:
    df = pitches.copy()
    df["team"] = _batting_team(df)
    g = df.groupby(["game_pk","season","team"], as_index=False)
    out = g.agg(
        pa=("at_bat_number", "nunique"),
        xwoba=("estimated_woba_using_speedangle", "mean"),
    )
    ev = df.dropna(subset=["events"])
    k = ev[ev["events"] == "strikeout"].groupby(["game_pk","team"]).size()
    bb = ev[ev["events"] == "walk"].groupby(["game_pk","team"]).size()
    out = out.set_index(["game_pk","team"])
    out["k_pct"] = (k / out["pa"]).fillna(0)
    out["bb_pct"] = (bb / out["pa"]).fillna(0)
    return out.reset_index()
```
Add `PITCHER_GAME_DDL` and `TEAM_GAME_DDL` to `warehouse.py` matching the produced columns + register in `init_schema`. CLI `build rollups --season`: read `SELECT * FROM statcast_pitches WHERE season = ?` into a df, compute both rollups, `replace_partition(..., "season")` each.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_rollups.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/mlb/rollups.py src/bblmlp/storage/warehouse.py src/bblmlp/cli.py tests/test_rollups.py
git commit -m "feat: statcast-derived pitcher/team game rollups + starters/lineups"
```

---

### Task 9: Live daily lineups/probables

**Files:**
- Create: `src/bblmlp/ingest/mlb/live.py`
- Modify: `src/bblmlp/storage/warehouse.py` (LIVE_LINEUPS_DDL + init_schema)
- Modify: `src/bblmlp/cli.py`
- Test: `tests/test_live.py`, `tests/fixtures/boxscore_sample.json`

**Interfaces:**
- Consumes: `replace_partition` (by `game_date`).
- Produces: `normalize_live_lineups(raw_games, game_date) -> pd.DataFrame` (`game_date, game_pk, team, player_id, batting_order, is_probable_pitcher`); thin `fetch_today_games(date)` (statsapi schedule with lineups/probables).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_live.py
from bblmlp.ingest.mlb.live import normalize_live_lineups

def test_normalize_live_lineups_flattens_probables_and_order():
    raw = [{
        "game_id": 7, "home_name": "SF", "away_name": "COL",
        "home_probable_pitcher_id": 500, "away_probable_pitcher_id": 900,
        "home_lineup": [{"player_id": 10, "order": 1}, {"player_id": 11, "order": 2}],
        "away_lineup": [{"player_id": 20, "order": 1}],
    }]
    out = normalize_live_lineups(raw, game_date="2026-07-09")
    probs = out[out["is_probable_pitcher"]]
    assert set(probs["player_id"]) == {500, 900}
    sf = out[(out["team"] == "SF") & (~out["is_probable_pitcher"])].sort_values("batting_order")
    assert list(sf["player_id"]) == [10, 11]
    assert (out["game_date"] == "2026-07-09").all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_live.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# src/bblmlp/ingest/mlb/live.py
from __future__ import annotations
import pandas as pd

def normalize_live_lineups(raw_games: list[dict], game_date: str) -> pd.DataFrame:
    rows = []
    for g in raw_games:
        gid = g.get("game_id")
        for side, team_key in (("home", "home_name"), ("away", "away_name")):
            team = g.get(team_key)
            pp = g.get(f"{side}_probable_pitcher_id")
            if pp is not None:
                rows.append({"game_date": game_date, "game_pk": gid, "team": team,
                             "player_id": pp, "batting_order": None,
                             "is_probable_pitcher": True})
            for spot in g.get(f"{side}_lineup", []) or []:
                rows.append({"game_date": game_date, "game_pk": gid, "team": team,
                             "player_id": spot.get("player_id"),
                             "batting_order": spot.get("order"),
                             "is_probable_pitcher": False})
    return pd.DataFrame(rows)

def fetch_today_games(date: str) -> list[dict]:
    import statsapi
    return statsapi.schedule(start_date=date, end_date=date)
```
Add `LIVE_LINEUPS_DDL` (`game_date DATE, game_pk BIGINT, team VARCHAR, player_id INTEGER, batting_order INTEGER, is_probable_pitcher BOOLEAN`) + register. CLI `ingest live` → `replace_partition(con, "live_lineups", df, "game_date")`.

> Note: `fetch_today_games` is a thin stub; enriching real posted lineups may need `statsapi.boxscore_data(game_pk)` per game. Keep the normalizer contract above; adapt the fetch to populate `{side}_lineup`/`{side}_probable_pitcher_id` when wiring live. Fetch is not unit-tested.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_live.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/mlb/live.py src/bblmlp/storage/warehouse.py src/bblmlp/cli.py tests/test_live.py
git commit -m "feat: live daily lineups/probables ingest"
```

---

### Task 10: `ingest all` orchestrator + full backfill

**Files:**
- Modify: `src/bblmlp/ingest/mlb/ingest.py`
- Modify: `src/bblmlp/cli.py`
- Test: `tests/test_ingest_mlb.py`

**Interfaces:**
- Consumes: every ingest module's fetch + normalize + write.
- Produces: `ingest_all(con, settings, *, fetchers) -> dict[str, int]` — runs sources in dependency order (players → games → statcast → fangraphs → standings → rollups) for `settings.data.backfill_seasons`, returning per-source row counts. `fetchers` is a dict of injected fetch fns so the orchestrator is testable without network.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ingest_mlb.py (add)
from bblmlp.ingest.mlb.ingest import ingest_all
from bblmlp.storage import connect, init_schema

def test_ingest_all_runs_sources_in_order_with_injected_fetchers(tmp_path):
    con = connect(tmp_path / "wh.duckdb"); init_schema(con)
    import pandas as pd
    fetchers = {
        "chadwick": lambda: pd.DataFrame({"key_mlbam":[111],"key_fangraphs":[11],
            "key_bbref":["a"],"key_retro":["r"],"name_first":["Ryan"],
            "name_last":["Feltner"],"mlb_played_first":[2021],"mlb_played_last":[2026]}),
        "schedule": lambda s, e: [{"game_id":1,"game_date":f"{s[:4]}-05-01","home_name":"SF",
            "away_name":"COL","status":"Final","home_score":3,"away_score":1}],
    }
    class S:  # minimal settings stub
        class data: warehouse_path=str(tmp_path/"wh.duckdb"); backfill_seasons=[2024]
    counts = ingest_all(con, S, fetchers=fetchers)
    assert counts["players"] == 1
    assert counts["games"] >= 1
    assert con.execute("SELECT count(*) FROM games").fetchone()[0] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_ingest_mlb.py -k ingest_all -v`
Expected: FAIL — `ingest_all` not defined.

- [ ] **Step 3: Write minimal implementation**

Implement `ingest_all(con, settings, *, fetchers)` calling, in order: players (fetch→normalize→`replace_all`), then per season the schedule ingest (reusing `ingest_range`, passing the loaded players df for id resolution), statcast/fangraphs/standings/rollups where their fetchers are supplied (skip any source whose fetcher is absent, so the test can inject a subset). Return the counts dict. Wire `bblmlp ingest all --backfill` / `--date` to build the real `fetchers` dict (chadwick, schedule, statcast, fangraphs, standings) and call `ingest_all`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_ingest_mlb.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/mlb/ingest.py src/bblmlp/cli.py tests/test_ingest_mlb.py
git commit -m "feat: ingest-all orchestrator across all MLB sources"
```

- [ ] **Step 6: Full-suite gate + real backfill (manual)**

Run: `uv run --no-sync pytest -q` → all green.
Then, once, the real comprehensive backfill:
```bash
rm -f data/warehouse.duckdb
uv run bblmlp ingest players
uv run bblmlp ingest all --backfill      # statcast + fangraphs + standings, all seasons
uv run bblmlp build rollups --season 2024  # (repeat per season, or fold into `all`)
```
Spot-check row counts per table in DuckDB; commit nothing (data is gitignored).

---

## Self-Review

**Spec coverage:** every table in the spec's §3 maps to a task — `statcast_pitches` widen → T2; `player_ids` → T3; `games` enrich → T4; `team_batting_season`/`team_pitching_season` → T5; `pitcher_stats_season`/`batter_stats_season` → T6; `standings` → T7; `pitcher_game_stats`/`team_game_stats` + derived starters/lineups → T8; `live_lineups` → T9; `ingest all` orchestration + backfill strategy (§4) → T10; DRY writers (§2 idempotency) → T1; CLI surface (§5) covered across T3/T5/T7/T8/T9/T10. Leakage boundary (§2) respected — no rolling stats in any task. FanGraphs leakage guard (§3.3) is Service 2's job, noted, not implemented here (correct).

**Placeholder scan:** no TBD/TODO; every code step shows real code. The two intentionally-thin spots (`ingest_all` wiring in T10 Step 3, live fetch in T9) describe exact call order and the tested contract rather than pasting full boilerplate — acceptable because their behavior is pinned by the injected-fetcher test (T10) and the normalizer test (T9).

**Type consistency:** `replace_partition(con, table, df, part_col)` / `replace_all(con, table, df)` used consistently T1–T10; `resolve_player_id(players, first, last, active_year=)` defined T3, consumed T4; `normalize_*` all return DataFrames tagged with `season` (or `game_date` for live); rollup column names in T8 interfaces match the DDL note and the test assertions.
