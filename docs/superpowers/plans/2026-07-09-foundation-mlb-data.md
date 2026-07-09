# Foundation + MLB Data Ingestion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the BBLMLP Python project and Service 1 — ingest MLB games (live schedule, historical results, and Statcast pitch data) into a local DuckDB warehouse queryable through one `bblmlp` CLI.

**Architecture:** A `uv`-managed Python package `bblmlp` with a Typer CLI. External data access is isolated in thin client wrappers; all normalization is done by **pure functions tested against recorded fixtures**; DuckDB is the single local store accessed through one `storage` module. This is Plan 1 of 4 for Phase 1 (single-game winners).

**Tech Stack:** Python 3.11+, uv, DuckDB, Typer, Pydantic v2, PyYAML, pandas, `MLB-StatsAPI` (import name `statsapi`), `pybaseball`, pytest.

## Global Constraints

- Python 3.11+; dependencies managed only through `uv` / `pyproject.toml`.
- Everything runs locally; no network calls in unit tests — external responses are mocked or read from committed fixtures under `tests/fixtures/`.
- Storage is a single DuckDB file at the path in `config/settings.yaml` (`data.warehouse_path`, default `data/warehouse.duckdb`). `data/` is gitignored.
- Money/price columns are integers in cents where they appear; not relevant in this plan.
- All external-data normalization is done by pure functions (input: raw dict/DataFrame, output: typed rows) so they are unit-testable without the network.
- Ingestion is idempotent: re-running upserts on `game_pk` (games) / pitch identity (statcast) must not duplicate rows.

---

### Task 1: Project scaffolding + CLI skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `src/bblmlp/__init__.py`
- Create: `src/bblmlp/cli.py`
- Create: `tests/__init__.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Produces: a Typer app `app` in `bblmlp.cli` with an `ingest` sub-app; console script `bblmlp = "bblmlp.cli:app"`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "bblmlp"
version = "0.1.0"
description = "Baseball ML prediction for Kalshi single-game markets"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.12",
    "duckdb>=1.1",
    "pydantic>=2.7",
    "pyyaml>=6.0",
    "pandas>=2.2",
    "MLB-StatsAPI>=1.7",
    "pybaseball>=2.2",
]

[project.scripts]
bblmlp = "bblmlp.cli:app"

[dependency-groups]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/bblmlp"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Create the package + CLI skeleton**

`src/bblmlp/__init__.py`:
```python
__version__ = "0.1.0"
```

`src/bblmlp/cli.py`:
```python
"""BBLMLP command-line interface."""
import typer

app = typer.Typer(help="Baseball ML prediction for Kalshi single-game markets.")
ingest_app = typer.Typer(help="Ingest data into the warehouse.")
app.add_typer(ingest_app, name="ingest")


@app.command()
def version() -> None:
    """Print the installed version."""
    from bblmlp import __version__

    typer.echo(__version__)


if __name__ == "__main__":
    app()
```

`tests/__init__.py`: (empty file)

- [ ] **Step 3: Write the failing test**

`tests/test_cli.py`:
```python
from typer.testing import CliRunner

from bblmlp.cli import app

runner = CliRunner()


def test_version_command_prints_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_ingest_group_exists():
    result = runner.invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 4: Install and run the tests**

Run: `uv sync && uv run pytest tests/test_cli.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/bblmlp/__init__.py src/bblmlp/cli.py tests/__init__.py tests/test_cli.py
git commit -m "feat: project scaffolding + CLI skeleton"
```

---

### Task 2: Configuration loading

**Files:**
- Create: `config/settings.yaml`
- Create: `src/bblmlp/config.py`
- Create: `tests/test_config.py`
- Create: `tests/fixtures/settings_min.yaml`

**Interfaces:**
- Produces:
  - `DataConfig` (Pydantic model): `warehouse_path: Path`, `snapshot_dir: Path`, `backfill_seasons: list[int]`.
  - `Settings` (Pydantic model): `data: DataConfig`; `model_config = ConfigDict(extra="allow")` so later plans add sections without breaking this loader.
  - `load_settings(path: str | Path = "config/settings.yaml") -> Settings`.

- [ ] **Step 1: Write `config/settings.yaml`**

```yaml
data:
  warehouse_path: data/warehouse.duckdb
  snapshot_dir: data/kalshi_snapshots
  backfill_seasons: [2021, 2022, 2023, 2024, 2025]
```

- [ ] **Step 2: Write the config module**

`src/bblmlp/config.py`:
```python
"""Configuration loading for BBLMLP."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class DataConfig(BaseModel):
    warehouse_path: Path
    snapshot_dir: Path
    backfill_seasons: list[int]


class Settings(BaseModel):
    model_config = ConfigDict(extra="allow")
    data: DataConfig


def load_settings(path: str | Path = "config/settings.yaml") -> Settings:
    raw = yaml.safe_load(Path(path).read_text())
    return Settings.model_validate(raw)
```

- [ ] **Step 3: Write the failing test**

`tests/fixtures/settings_min.yaml`:
```yaml
data:
  warehouse_path: /tmp/bblmlp_test.duckdb
  snapshot_dir: /tmp/bblmlp_snaps
  backfill_seasons: [2024, 2025]
```

`tests/test_config.py`:
```python
from pathlib import Path

from bblmlp.config import load_settings


def test_load_settings_parses_data_section():
    s = load_settings("tests/fixtures/settings_min.yaml")
    assert s.data.warehouse_path == Path("/tmp/bblmlp_test.duckdb")
    assert s.data.backfill_seasons == [2024, 2025]


def test_extra_top_level_sections_are_allowed():
    # later plans add kalshi/model/staking sections; loader must not reject them
    import tempfile

    text = (
        "data:\n"
        "  warehouse_path: a.duckdb\n"
        "  snapshot_dir: snaps\n"
        "  backfill_seasons: [2025]\n"
        "future_section:\n"
        "  anything: true\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(text)
        p = f.name
    s = load_settings(p)
    assert s.data.backfill_seasons == [2025]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_config.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add config/settings.yaml src/bblmlp/config.py tests/test_config.py tests/fixtures/settings_min.yaml
git commit -m "feat: settings.yaml + config loader"
```

---

### Task 3: DuckDB storage layer + schema

**Files:**
- Create: `src/bblmlp/storage/__init__.py`
- Create: `src/bblmlp/storage/warehouse.py`
- Modify: `src/bblmlp/cli.py` (add `init-db` command)
- Create: `tests/test_warehouse.py`

**Interfaces:**
- Consumes: `Settings` / `load_settings` from Task 2.
- Produces:
  - `connect(path: str | Path) -> duckdb.DuckDBPyConnection`
  - `init_schema(con) -> None` — creates tables `games`, `statcast_pitches` if absent (idempotent).
  - `table_names(con) -> set[str]`
  - `upsert_games(con, rows: list[dict]) -> int` — insert-or-replace on `game_pk`, returns row count written.
  - `Game` fields (dict keys used everywhere): `game_pk:int, season:int, game_date:str(YYYY-MM-DD), game_datetime:str|None, home_team:str, away_team:str, home_team_id:int, away_team_id:int, home_probable_pitcher:str|None, away_probable_pitcher:str|None, venue:str|None, status:str, home_score:int|None, away_score:int|None, home_win:int|None`.

- [ ] **Step 1: Write the warehouse module**

`src/bblmlp/storage/__init__.py`:
```python
from bblmlp.storage.warehouse import (
    connect,
    init_schema,
    table_names,
    upsert_games,
)

__all__ = ["connect", "init_schema", "table_names", "upsert_games"]
```

`src/bblmlp/storage/warehouse.py`:
```python
"""DuckDB warehouse: connection, schema, and idempotent writes."""
from __future__ import annotations

from pathlib import Path

import duckdb

GAMES_DDL = """
CREATE TABLE IF NOT EXISTS games (
    game_pk BIGINT PRIMARY KEY,
    season INTEGER NOT NULL,
    game_date DATE NOT NULL,
    game_datetime TIMESTAMP,
    home_team VARCHAR NOT NULL,
    away_team VARCHAR NOT NULL,
    home_team_id INTEGER,
    away_team_id INTEGER,
    home_probable_pitcher VARCHAR,
    away_probable_pitcher VARCHAR,
    venue VARCHAR,
    status VARCHAR,
    home_score INTEGER,
    away_score INTEGER,
    home_win INTEGER
);
"""

STATCAST_DDL = """
CREATE TABLE IF NOT EXISTS statcast_pitches (
    game_pk BIGINT,
    game_date DATE,
    season INTEGER,
    pitcher INTEGER,
    batter INTEGER,
    events VARCHAR,
    description VARCHAR,
    pitch_type VARCHAR,
    release_speed DOUBLE,
    estimated_woba_using_speedangle DOUBLE,
    at_bat_number INTEGER,
    pitch_number INTEGER
);
"""

_GAME_COLUMNS = [
    "game_pk", "season", "game_date", "game_datetime", "home_team", "away_team",
    "home_team_id", "away_team_id", "home_probable_pitcher", "away_probable_pitcher",
    "venue", "status", "home_score", "away_score", "home_win",
]


def connect(path: str | Path) -> duckdb.DuckDBPyConnection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(p))


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(GAMES_DDL)
    con.execute(STATCAST_DDL)


def table_names(con: duckdb.DuckDBPyConnection) -> set[str]:
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {r[0] for r in rows}


def upsert_games(con: duckdb.DuckDBPyConnection, rows: list[dict]) -> int:
    if not rows:
        return 0
    placeholders = ", ".join(["?"] * len(_GAME_COLUMNS))
    cols = ", ".join(_GAME_COLUMNS)
    con.execute("BEGIN TRANSACTION")
    con.executemany(
        f"INSERT OR REPLACE INTO games ({cols}) VALUES ({placeholders})",
        [[r.get(c) for c in _GAME_COLUMNS] for r in rows],
    )
    con.execute("COMMIT")
    return len(rows)
```

- [ ] **Step 2: Add `init-db` CLI command**

In `src/bblmlp/cli.py`, add after the `version` command:
```python
@app.command("init-db")
def init_db() -> None:
    """Create the DuckDB warehouse and its tables."""
    from bblmlp.config import load_settings
    from bblmlp.storage import connect, init_schema

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    con.close()
    typer.echo(f"Initialized warehouse at {settings.data.warehouse_path}")
```

- [ ] **Step 3: Write the failing test**

`tests/test_warehouse.py`:
```python
from bblmlp.storage import connect, init_schema, table_names, upsert_games


def _game(pk: int, home_win: int | None = None) -> dict:
    return {
        "game_pk": pk, "season": 2025, "game_date": "2025-07-04",
        "game_datetime": "2025-07-04T18:05:00Z", "home_team": "Dodgers",
        "away_team": "Giants", "home_team_id": 119, "away_team_id": 137,
        "home_probable_pitcher": "A B", "away_probable_pitcher": "C D",
        "venue": "Dodger Stadium", "status": "Final",
        "home_score": 5, "away_score": 3, "home_win": home_win,
    }


def test_init_schema_creates_tables(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    assert {"games", "statcast_pitches"}.issubset(table_names(con))


def test_upsert_games_is_idempotent(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    upsert_games(con, [_game(1, home_win=1)])
    upsert_games(con, [_game(1, home_win=1)])  # same pk again
    count = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    assert count == 1


def test_upsert_games_replaces_on_conflict(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    upsert_games(con, [_game(1, home_win=None)])   # scheduled, no result
    upsert_games(con, [_game(1, home_win=1)])       # later: final
    val = con.execute("SELECT home_win FROM games WHERE game_pk = 1").fetchone()[0]
    assert val == 1
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_warehouse.py -v`
Expected: all three PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/storage/ src/bblmlp/cli.py tests/test_warehouse.py
git commit -m "feat: DuckDB warehouse, schema, idempotent game upsert + init-db command"
```

---

### Task 4: MLB StatsAPI client + schedule normalizer

**Files:**
- Create: `src/bblmlp/ingest/__init__.py`
- Create: `src/bblmlp/ingest/mlb/__init__.py`
- Create: `src/bblmlp/ingest/mlb/statsapi_client.py`
- Create: `src/bblmlp/ingest/mlb/schedule.py`
- Create: `scripts/capture_schedule_fixture.py`
- Create: `tests/fixtures/statsapi_schedule.json` (recorded, see Step 1)
- Create: `tests/test_schedule_normalizer.py`

**Interfaces:**
- Produces:
  - `statsapi_client.fetch_schedule(start_date: str, end_date: str) -> list[dict]` — thin wrapper over `statsapi.schedule(...)` (the only network call; not unit-tested).
  - `schedule.normalize_schedule(raw_games: list[dict], season: int) -> list[dict]` — pure; returns `Game` dicts (keys defined in Task 3).
  - `schedule.compute_home_win(home_score, away_score, status) -> int | None` — 1/0 if the game is Final and decided, else None.

- [ ] **Step 1: Record a real fixture (setup — one network call, not part of tests)**

`scripts/capture_schedule_fixture.py`:
```python
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
```

Run: `uv run python scripts/capture_schedule_fixture.py`
Expected: writes `tests/fixtures/statsapi_schedule.json` with a non-empty list. Open it and confirm each entry has keys including `game_id`, `game_datetime`, `home_name`, `away_name`, `home_id`, `away_id`, `status`, `home_score`, `away_score`, `home_probable_pitcher`, `away_probable_pitcher`, `venue_name`. If a key name differs in the recorded data, use the recorded name in Step 3's normalizer.

- [ ] **Step 2: Write the failing test**

`tests/test_schedule_normalizer.py`:
```python
import json
from pathlib import Path

from bblmlp.ingest.mlb.schedule import compute_home_win, normalize_schedule

RAW = json.loads(Path("tests/fixtures/statsapi_schedule.json").read_text())


def test_normalize_returns_game_rows_with_required_keys():
    rows = normalize_schedule(RAW, season=2024)
    assert len(rows) == len(RAW)
    required = {
        "game_pk", "season", "game_date", "home_team", "away_team",
        "home_team_id", "away_team_id", "status", "home_score",
        "away_score", "home_win",
    }
    for row in rows:
        assert required.issubset(row.keys())
        assert row["season"] == 2024
        assert isinstance(row["game_pk"], int)


def test_compute_home_win_decided_final():
    assert compute_home_win(5, 3, "Final") == 1
    assert compute_home_win(2, 6, "Final") == 0


def test_compute_home_win_unplayed_or_tie_is_none():
    assert compute_home_win(None, None, "Scheduled") is None
    assert compute_home_win(4, 4, "Final") is None  # tie => undecided
    assert compute_home_win(5, 3, "Scheduled") is None
```

- [ ] **Step 3: Write the client + normalizer**

`src/bblmlp/ingest/__init__.py`: (empty file)
`src/bblmlp/ingest/mlb/__init__.py`: (empty file)

`src/bblmlp/ingest/mlb/statsapi_client.py`:
```python
"""Thin wrapper over MLB-StatsAPI. The only place that touches the network."""
from __future__ import annotations

import statsapi


def fetch_schedule(start_date: str, end_date: str) -> list[dict]:
    """Return raw StatsAPI schedule dicts for the inclusive date range."""
    return statsapi.schedule(start_date=start_date, end_date=end_date)
```

`src/bblmlp/ingest/mlb/schedule.py`:
```python
"""Pure normalization of StatsAPI schedule dicts into Game rows."""
from __future__ import annotations


def compute_home_win(home_score, away_score, status) -> int | None:
    if status != "Final" or home_score is None or away_score is None:
        return None
    if home_score == away_score:
        return None
    return 1 if home_score > away_score else 0


def _game_date(raw: dict) -> str:
    # statsapi provides "game_date" (YYYY-MM-DD); fall back to datetime prefix.
    if raw.get("game_date"):
        return str(raw["game_date"])
    dt = raw.get("game_datetime") or ""
    return dt[:10]


def normalize_schedule(raw_games: list[dict], season: int) -> list[dict]:
    rows: list[dict] = []
    for raw in raw_games:
        home_score = raw.get("home_score")
        away_score = raw.get("away_score")
        status = raw.get("status")
        rows.append(
            {
                "game_pk": int(raw["game_id"]),
                "season": season,
                "game_date": _game_date(raw),
                "game_datetime": raw.get("game_datetime"),
                "home_team": raw.get("home_name"),
                "away_team": raw.get("away_name"),
                "home_team_id": raw.get("home_id"),
                "away_team_id": raw.get("away_id"),
                "home_probable_pitcher": raw.get("home_probable_pitcher") or None,
                "away_probable_pitcher": raw.get("away_probable_pitcher") or None,
                "venue": raw.get("venue_name"),
                "status": status,
                "home_score": home_score,
                "away_score": away_score,
                "home_win": compute_home_win(home_score, away_score, status),
            }
        )
    return rows
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_schedule_normalizer.py -v`
Expected: all PASS. (If a KeyError appears, a fixture key name differs — align the normalizer to the recorded fixture keys.)

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest tests/test_schedule_normalizer.py tests/fixtures/statsapi_schedule.json scripts/capture_schedule_fixture.py
git commit -m "feat: StatsAPI client + tested schedule normalizer"
```

---

### Task 5: Live ingestion command (`ingest mlb --live`)

**Files:**
- Create: `src/bblmlp/ingest/mlb/ingest.py`
- Modify: `src/bblmlp/cli.py` (add `ingest mlb` command)
- Create: `tests/test_ingest_mlb.py`

**Interfaces:**
- Consumes: `fetch_schedule` (Task 4), `normalize_schedule` (Task 4), `connect`/`init_schema`/`upsert_games` (Task 3).
- Produces:
  - `ingest.ingest_range(con, fetch, start_date: str, end_date: str, season: int) -> int` — fetch → normalize → upsert; `fetch` is injected (dependency injection) so it is testable with a fake. Returns rows written.
  - CLI: `bblmlp ingest mlb --live` (today) and `--date YYYY-MM-DD`.

- [ ] **Step 1: Write the failing test**

`tests/test_ingest_mlb.py`:
```python
import json
from pathlib import Path

from bblmlp.ingest.mlb.ingest import ingest_range
from bblmlp.storage import connect, init_schema

RAW = json.loads(Path("tests/fixtures/statsapi_schedule.json").read_text())


def test_ingest_range_writes_games(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)

    def fake_fetch(start_date, end_date):
        return RAW

    written = ingest_range(con, fake_fetch, "2024-07-04", "2024-07-04", season=2024)
    assert written == len(RAW)
    count = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    assert count == len(RAW)


def test_ingest_range_is_idempotent(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)

    def fake_fetch(start_date, end_date):
        return RAW

    ingest_range(con, fake_fetch, "2024-07-04", "2024-07-04", season=2024)
    ingest_range(con, fake_fetch, "2024-07-04", "2024-07-04", season=2024)
    count = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    assert count == len(RAW)
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_ingest_mlb.py -v`
Expected: FAIL with `ModuleNotFoundError: bblmlp.ingest.mlb.ingest`.

- [ ] **Step 3: Write the ingest function**

`src/bblmlp/ingest/mlb/ingest.py`:
```python
"""Orchestrate fetch -> normalize -> upsert for MLB games."""
from __future__ import annotations

from typing import Callable

from bblmlp.ingest.mlb.schedule import normalize_schedule
from bblmlp.storage import upsert_games

FetchFn = Callable[[str, str], list[dict]]


def ingest_range(
    con, fetch: FetchFn, start_date: str, end_date: str, season: int
) -> int:
    raw = fetch(start_date, end_date)
    rows = normalize_schedule(raw, season=season)
    return upsert_games(con, rows)
```

- [ ] **Step 4: Add the CLI command**

In `src/bblmlp/cli.py`, add:
```python
@ingest_app.command("mlb")
def ingest_mlb(
    live: bool = typer.Option(False, "--live", help="Ingest today's schedule."),
    date: str = typer.Option(None, "--date", help="Ingest a single date (YYYY-MM-DD)."),
) -> None:
    """Ingest MLB games into the warehouse."""
    import datetime as _dt

    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.ingest import ingest_range
    from bblmlp.ingest.mlb.statsapi_client import fetch_schedule
    from bblmlp.storage import connect, init_schema

    target = date or (_dt.date.today().isoformat() if live else None)
    if target is None:
        raise typer.BadParameter("Provide --live or --date YYYY-MM-DD")

    season = int(target[:4])
    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    written = ingest_range(con, fetch_schedule, target, target, season)
    con.close()
    typer.echo(f"Ingested {written} games for {target}")
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_ingest_mlb.py -v`
Expected: both PASS.

- [ ] **Step 6: Manual smoke test (real network)**

Run: `uv run bblmlp init-db && uv run bblmlp ingest mlb --date 2024-07-04`
Expected: prints `Ingested N games for 2024-07-04` with N > 0. Then:
`uv run python -c "import duckdb; print(duckdb.connect('data/warehouse.duckdb').execute('select count(*), sum(home_win) from games').fetchall())"`
Expected: a non-zero game count and a numeric home-win sum.

- [ ] **Step 7: Commit**

```bash
git add src/bblmlp/ingest/mlb/ingest.py src/bblmlp/cli.py tests/test_ingest_mlb.py
git commit -m "feat: ingest mlb games command (live + single date)"
```

---

### Task 6: Historical backfill (`ingest mlb --backfill`)

**Files:**
- Modify: `src/bblmlp/ingest/mlb/ingest.py` (add `season_date_range`, `ingest_seasons`)
- Modify: `src/bblmlp/cli.py` (add `--backfill` flag)
- Modify: `tests/test_ingest_mlb.py` (add range/backfill tests)

**Interfaces:**
- Consumes: `ingest_range` (Task 5), `Settings.data.backfill_seasons` (Task 2).
- Produces:
  - `season_date_range(season: int) -> tuple[str, str]` — returns `("{season}-03-01", "{season}-11-30")` (covers spring→postseason; StatsAPI clamps to actual games).
  - `ingest_seasons(con, fetch, seasons: list[int]) -> int` — sums rows written across seasons.

- [ ] **Step 1: Write the failing test (append to `tests/test_ingest_mlb.py`)**

```python
from bblmlp.ingest.mlb.ingest import ingest_seasons, season_date_range


def test_season_date_range():
    assert season_date_range(2024) == ("2024-03-01", "2024-11-30")


def test_ingest_seasons_calls_fetch_per_season(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    calls = []

    def fake_fetch(start_date, end_date):
        calls.append((start_date, end_date))
        return RAW  # reuse fixture; pks collide across seasons but upsert dedupes

    ingest_seasons(con, fake_fetch, [2023, 2024])
    assert calls == [("2023-03-01", "2023-11-30"), ("2024-03-01", "2024-11-30")]
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_ingest_mlb.py -k "season" -v`
Expected: FAIL (functions not defined).

- [ ] **Step 3: Implement in `src/bblmlp/ingest/mlb/ingest.py`**

Append:
```python
def season_date_range(season: int) -> tuple[str, str]:
    return (f"{season}-03-01", f"{season}-11-30")


def ingest_seasons(con, fetch: FetchFn, seasons: list[int]) -> int:
    total = 0
    for season in seasons:
        start, end = season_date_range(season)
        total += ingest_range(con, fetch, start, end, season)
    return total
```

- [ ] **Step 4: Add `--backfill` to the CLI**

Replace the entire `ingest_mlb` function in `src/bblmlp/cli.py` with this version (adds the `--backfill` branch and shares imports across both branches):
```python
@ingest_app.command("mlb")
def ingest_mlb(
    live: bool = typer.Option(False, "--live", help="Ingest today's schedule."),
    date: str = typer.Option(None, "--date", help="Ingest a single date (YYYY-MM-DD)."),
    backfill: bool = typer.Option(
        False, "--backfill", help="Backfill all seasons in settings."
    ),
) -> None:
    """Ingest MLB games into the warehouse."""
    import datetime as _dt

    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.ingest import ingest_range, ingest_seasons
    from bblmlp.ingest.mlb.statsapi_client import fetch_schedule
    from bblmlp.storage import connect, init_schema

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)

    if backfill:
        written = ingest_seasons(con, fetch_schedule, settings.data.backfill_seasons)
        con.close()
        typer.echo(f"Backfilled {written} games across {settings.data.backfill_seasons}")
        return

    target = date or (_dt.date.today().isoformat() if live else None)
    if target is None:
        con.close()
        raise typer.BadParameter("Provide --live, --date YYYY-MM-DD, or --backfill")

    season = int(target[:4])
    written = ingest_range(con, fetch_schedule, target, target, season)
    con.close()
    typer.echo(f"Ingested {written} games for {target}")
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_ingest_mlb.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bblmlp/ingest/mlb/ingest.py src/bblmlp/cli.py tests/test_ingest_mlb.py
git commit -m "feat: historical season backfill for MLB games"
```

---

### Task 7: Statcast backfill (`ingest statcast`)

**Files:**
- Create: `src/bblmlp/ingest/mlb/statcast.py`
- Modify: `src/bblmlp/cli.py` (add `ingest statcast` command)
- Create: `tests/test_statcast.py`

**Interfaces:**
- Consumes: `connect`/`init_schema` (Task 3).
- Produces:
  - `statcast.STATCAST_COLUMNS: list[str]` — the subset of pybaseball Statcast columns we persist (matches `statcast_pitches` DDL).
  - `statcast.normalize_statcast(df: pandas.DataFrame, season: int) -> pandas.DataFrame` — pure; selects/renames columns, adds `season`, drops rows with null `game_pk`.
  - `statcast.write_statcast(con, df) -> int` — appends rows to `statcast_pitches`, returns count.
  - CLI: `bblmlp ingest statcast --season YYYY` (uses `pybaseball.statcast` for the season range under the hood).

- [ ] **Step 1: Write the failing test**

`tests/test_statcast.py`:
```python
import pandas as pd

from bblmlp.ingest.mlb.statcast import normalize_statcast, write_statcast
from bblmlp.storage import connect, init_schema


def _raw_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "game_pk": [745123, 745123, None],
            "game_date": ["2024-07-04", "2024-07-04", "2024-07-04"],
            "pitcher": [111, 111, 222],
            "batter": [333, 444, 555],
            "events": ["strikeout", None, "single"],
            "description": ["swinging_strike", "ball", "hit_into_play"],
            "pitch_type": ["FF", "SL", "CH"],
            "release_speed": [95.1, 84.3, 82.0],
            "estimated_woba_using_speedangle": [0.0, None, 0.45],
            "at_bat_number": [1, 1, 2],
            "pitch_number": [3, 1, 1],
            "extra_col_ignored": ["a", "b", "c"],
        }
    )


def test_normalize_drops_null_game_pk_and_adds_season():
    out = normalize_statcast(_raw_df(), season=2024)
    assert (out["season"] == 2024).all()
    assert out["game_pk"].notna().all()
    assert len(out) == 2  # null game_pk row dropped
    assert "extra_col_ignored" not in out.columns


def test_write_statcast_appends_rows(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    out = normalize_statcast(_raw_df(), season=2024)
    n = write_statcast(con, out)
    assert n == 2
    total = con.execute("SELECT COUNT(*) FROM statcast_pitches").fetchone()[0]
    assert total == 2
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_statcast.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `src/bblmlp/ingest/mlb/statcast.py`**

```python
"""Statcast ingestion via pybaseball, normalized into statcast_pitches."""
from __future__ import annotations

import pandas as pd

STATCAST_COLUMNS = [
    "game_pk", "game_date", "season", "pitcher", "batter", "events",
    "description", "pitch_type", "release_speed",
    "estimated_woba_using_speedangle", "at_bat_number", "pitch_number",
]


def normalize_statcast(df: pd.DataFrame, season: int) -> pd.DataFrame:
    df = df.copy()
    df["season"] = season
    df = df[df["game_pk"].notna()]
    keep = [c for c in STATCAST_COLUMNS if c in df.columns]
    out = df[keep].copy()
    out["game_pk"] = out["game_pk"].astype("int64")
    return out


def write_statcast(con, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    con.register("df_statcast", df)
    cols = ", ".join(df.columns)
    con.execute(f"INSERT INTO statcast_pitches ({cols}) SELECT {cols} FROM df_statcast")
    con.unregister("df_statcast")
    return len(df)


def fetch_statcast_season(season: int) -> pd.DataFrame:
    """Network call: pull a full season of Statcast via pybaseball."""
    from pybaseball import statcast

    return statcast(start_dt=f"{season}-03-01", end_dt=f"{season}-11-30")
```

- [ ] **Step 4: Add the CLI command**

In `src/bblmlp/cli.py`, add:
```python
@ingest_app.command("statcast")
def ingest_statcast(season: int = typer.Option(..., "--season")) -> None:
    """Backfill a season of Statcast pitch data."""
    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.statcast import (
        fetch_statcast_season,
        normalize_statcast,
        write_statcast,
    )
    from bblmlp.storage import connect, init_schema

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    raw = fetch_statcast_season(season)
    out = normalize_statcast(raw, season=season)
    n = write_statcast(con, out)
    con.close()
    typer.echo(f"Wrote {n} statcast rows for {season}")
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_statcast.py -v`
Expected: both PASS.

- [ ] **Step 6: Full suite + commit**

Run: `uv run pytest -v`
Expected: entire suite PASS.
```bash
git add src/bblmlp/ingest/mlb/statcast.py src/bblmlp/cli.py tests/test_statcast.py
git commit -m "feat: statcast season backfill into warehouse"
```

---

## Definition of done (Plan 1)

- `uv run pytest` is green.
- `uv run bblmlp init-db` creates `data/warehouse.duckdb` with `games` + `statcast_pitches`.
- `uv run bblmlp ingest mlb --live` writes today's games; `--backfill` fills configured seasons; `ingest statcast --season 2024` lands pitch data.
- Re-running any ingest command does not duplicate rows.

**Next:** Plan 2 — feature engineering (as-of tables) + Elo→LightGBM calibrated game-winner model, written once this warehouse exists so features are grounded in real columns.
```
