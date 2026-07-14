# Rolling-Window Feature Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `src/bblmlp/features/rolling.py`, materializing as-of-safe trailing rolling-window
stats (team + pitcher grain) from the existing `team_game_stats`/`pitcher_game_stats` rollup
tables into two new warehouse tables, driven by a new `bblmlp build features --season <year>` CLI
command.

**Architecture:** Two concrete DuckDB-SQL builder functions (one per grain, no shared generic
engine — see spec §2 for why). Each registers its input DataFrames against a DuckDB connection,
runs a single SQL query using named `WINDOW` clauses with `ROWS BETWEEN N PRECEDING AND 1
PRECEDING`, and returns the result as a DataFrame for the existing `replace_partition` writer.

**Tech Stack:** Python, DuckDB (`duckdb` Python API, SQL window functions), pandas, pytest, Typer
CLI — all already in the project's stack, no new dependencies.

## Global Constraints

- Design source of truth: `docs/superpowers/specs/2026-07-13-rolling-window-features-design.md`.
  Every requirement in that spec must map to a task below.
- Window computation MUST use DuckDB SQL window functions, not pandas `.rolling()` or Python
  loops over rows.
- Ordering key is `(game_date, game_datetime, game_pk)` — join both rollup tables to `games` to
  get `game_date`/`game_datetime`, neither of which the rollup tables store themselves.
- `k_pct`/`bb_pct` reconstruction at team grain: `sum(rate * pa) / sum(pa)` over the window — never
  `mean(per-game rate)`. `xwoba` at team grain uses the same PA-weighted formula as a **documented
  approximation** (state this in the function docstring, not just the spec).
- Pitcher grain has raw counts already (`k`, `bb`, `whiffs`, `pitches`, `batters_faced`) — direct
  `sum(numerator)/sum(denominator)`, no reconstruction needed. `avg_velo` is a plain trailing mean.
- Cold start (partial windows, shrinkage) is explicitly OUT of scope — leave DuckDB's natural
  partial-window behavior as-is (fewer rows early, `NULL` only with zero prior games).
- Run tests with `uv run --no-sync pytest -q`, never bare `pytest` (see CLAUDE.md's `.pth`
  gotcha). Existing suite is 72 tests; it must stay green throughout.
- Follow existing conventions exactly: `replace_partition`-based idempotent writes, explicit table
  DDL in `warehouse.py` added to `init_schema`, Typer `build_app.command(...)` pattern in `cli.py`,
  fixture-based pure-function tests with no network and no real warehouse file (except the CLI
  integration test, which uses `tmp_path`).

---

## Task 1: `team_features` and `pitcher_features` table DDL

**Files:**
- Modify: `src/bblmlp/storage/warehouse.py` (add two DDL constants + register in `init_schema`)
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Produces: `team_features` table with columns `game_pk BIGINT, season INTEGER, team VARCHAR,
  k_pct_30 DOUBLE, bb_pct_30 DOUBLE, xwoba_30 DOUBLE, n_games_30 INTEGER, k_pct_162 DOUBLE,
  bb_pct_162 DOUBLE, xwoba_162 DOUBLE, n_games_162 INTEGER`.
- Produces: `pitcher_features` table with columns `game_pk BIGINT, season INTEGER, pitcher
  INTEGER, is_starter BOOLEAN, k_pct_10 DOUBLE, bb_pct_10 DOUBLE, swstr_pct_10 DOUBLE, avg_velo_10
  DOUBLE, n_games_10 INTEGER, k_pct_35 DOUBLE, bb_pct_35 DOUBLE, swstr_pct_35 DOUBLE, avg_velo_35
  DOUBLE, n_games_35 INTEGER, k_pct_75 DOUBLE, bb_pct_75 DOUBLE, swstr_pct_75 DOUBLE, avg_velo_75
  DOUBLE, n_games_75 INTEGER`.
- Both tables are created via `init_schema(con)`, matching how `team_game_stats`/
  `pitcher_game_stats` already work (`replace_partition` assumes the table exists — it does not
  create it).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_warehouse.py`:

```python
def test_init_schema_creates_team_features_table(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    assert "team_features" in table_names(con)
    cols = [r[0] for r in con.execute("DESCRIBE team_features").fetchall()]
    assert cols == [
        "game_pk", "season", "team",
        "k_pct_30", "bb_pct_30", "xwoba_30", "n_games_30",
        "k_pct_162", "bb_pct_162", "xwoba_162", "n_games_162",
    ]


def test_init_schema_creates_pitcher_features_table(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    assert "pitcher_features" in table_names(con)
    cols = [r[0] for r in con.execute("DESCRIBE pitcher_features").fetchall()]
    assert cols == [
        "game_pk", "season", "pitcher", "is_starter",
        "k_pct_10", "bb_pct_10", "swstr_pct_10", "avg_velo_10", "n_games_10",
        "k_pct_35", "bb_pct_35", "swstr_pct_35", "avg_velo_35", "n_games_35",
        "k_pct_75", "bb_pct_75", "swstr_pct_75", "avg_velo_75", "n_games_75",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_warehouse.py -k "team_features or pitcher_features" -v`
Expected: FAIL — `assert "team_features" in table_names(con)` fails (table doesn't exist yet).

- [ ] **Step 3: Add the DDL**

In `src/bblmlp/storage/warehouse.py`, add after `PARK_REFERENCE_DDL` (around line 194):

```python
TEAM_FEATURES_DDL = """
CREATE TABLE IF NOT EXISTS team_features (
    game_pk BIGINT,
    season INTEGER,
    team VARCHAR,
    k_pct_30 DOUBLE,
    bb_pct_30 DOUBLE,
    xwoba_30 DOUBLE,
    n_games_30 INTEGER,
    k_pct_162 DOUBLE,
    bb_pct_162 DOUBLE,
    xwoba_162 DOUBLE,
    n_games_162 INTEGER
);
"""

PITCHER_FEATURES_DDL = """
CREATE TABLE IF NOT EXISTS pitcher_features (
    game_pk BIGINT,
    season INTEGER,
    pitcher INTEGER,
    is_starter BOOLEAN,
    k_pct_10 DOUBLE,
    bb_pct_10 DOUBLE,
    swstr_pct_10 DOUBLE,
    avg_velo_10 DOUBLE,
    n_games_10 INTEGER,
    k_pct_35 DOUBLE,
    bb_pct_35 DOUBLE,
    swstr_pct_35 DOUBLE,
    avg_velo_35 DOUBLE,
    n_games_35 INTEGER,
    k_pct_75 DOUBLE,
    bb_pct_75 DOUBLE,
    swstr_pct_75 DOUBLE,
    avg_velo_75 DOUBLE,
    n_games_75 INTEGER
);
"""
```

Then in `init_schema` (around line 210-219), add both after `con.execute(PARK_REFERENCE_DDL)`:

```python
    con.execute(TEAM_FEATURES_DDL)
    con.execute(PITCHER_FEATURES_DDL)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_warehouse.py -v`
Expected: PASS — all `test_warehouse.py` tests pass, including the two new ones.

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/storage/warehouse.py tests/test_warehouse.py
git commit -m "feat: add team_features and pitcher_features table DDL"
```

---

## Task 2: `team_rolling_features` builder

**Files:**
- Create: `src/bblmlp/features/__init__.py` (empty)
- Create: `src/bblmlp/features/rolling.py`
- Test: `tests/test_features_rolling.py`

**Interfaces:**
- Consumes: nothing from other tasks (operates on plain DataFrames + a `duckdb.DuckDBPyConnection`
  the caller provides — no dependency on `warehouse.py`'s tables existing).
- Produces: `TEAM_WINDOWS: tuple[int, ...] = (30, 162)` and
  `team_rolling_features(con: duckdb.DuckDBPyConnection, team_game_stats: pd.DataFrame, games:
  pd.DataFrame) -> pd.DataFrame`, returning columns `game_pk, season, team, k_pct_30, bb_pct_30,
  xwoba_30, n_games_30, k_pct_162, bb_pct_162, xwoba_162, n_games_162` (exact order), ordered by
  `(game_date, game_datetime, game_pk)`. `games` must contain at least `game_pk`, `game_date`,
  `game_datetime`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_features_rolling.py`:

```python
import duckdb
import pandas as pd
import pytest

from bblmlp.features.rolling import team_rolling_features


def _team_game_stats():
    # One team (NYY), 4 consecutive games, 2-day gap before game 3 to prove
    # the window is games-based, not calendar-based.
    return pd.DataFrame({
        "game_pk": [1, 2, 3, 4],
        "season": [2024] * 4,
        "team": ["NYY"] * 4,
        "pa": [36, 41, 42, 35],
        "xwoba": [0.30, 0.25, 0.40, 0.20],
        "k_pct": [0.250000, 0.170732, 0.261905, 0.142857],
        "bb_pct": [0.055556, 0.024390, 0.142857, 0.085714],
    })


def _games():
    return pd.DataFrame({
        "game_pk": [1, 2, 3, 4],
        "game_date": ["2024-03-15", "2024-03-16", "2024-03-19", "2024-03-20"],
        "game_datetime": [
            "2024-03-15T18:00", "2024-03-16T18:00", "2024-03-19T18:00", "2024-03-20T18:00",
        ],
    })


def test_first_game_has_no_history():
    con = duckdb.connect(":memory:")
    out = team_rolling_features(con, _team_game_stats(), _games())
    row = out[out["game_pk"] == 1].iloc[0]
    assert row["n_games_30"] == 0
    assert pd.isna(row["k_pct_30"])


def test_second_game_trailing_equals_first_games_own_rate():
    con = duckdb.connect(":memory:")
    out = team_rolling_features(con, _team_game_stats(), _games())
    row = out[out["game_pk"] == 2].iloc[0]
    assert row["n_games_30"] == 1
    assert row["k_pct_30"] == pytest.approx(0.250000)
    assert row["bb_pct_30"] == pytest.approx(0.055556)


def test_rate_reconstruction_is_pa_weighted_sum_not_mean_of_rates():
    con = duckdb.connect(":memory:")
    out = team_rolling_features(con, _team_game_stats(), _games())
    row = out[out["game_pk"] == 3].iloc[0]
    # trailing window over games 1,2 (30 PRECEDING covers everything before game 3)
    expected_k_pct = (0.250000 * 36 + 0.170732 * 41) / (36 + 41)
    expected_xwoba = (0.30 * 36 + 0.25 * 41) / (36 + 41)
    assert row["k_pct_30"] == pytest.approx(expected_k_pct)
    assert row["xwoba_30"] == pytest.approx(expected_xwoba)
    assert row["n_games_30"] == 2


def test_leakage_perturbing_a_games_own_stats_does_not_change_its_own_row():
    con = duckdb.connect(":memory:")
    baseline = team_rolling_features(con, _team_game_stats(), _games())
    baseline_row3 = baseline[baseline["game_pk"] == 3].iloc[0]

    perturbed = _team_game_stats()
    perturbed.loc[perturbed["game_pk"] == 3, "k_pct"] = 0.999  # blow up game 3's own value
    con2 = duckdb.connect(":memory:")
    out = team_rolling_features(con2, perturbed, _games())
    row3 = out[out["game_pk"] == 3].iloc[0]

    # game 3's own trailing feature must be unaffected by game 3's own perturbed value
    assert row3["k_pct_30"] == pytest.approx(baseline_row3["k_pct_30"])
    # but game 4's trailing feature, which looks back at game 3, must move
    row4 = out[out["game_pk"] == 4].iloc[0]
    baseline_row4 = baseline[baseline["game_pk"] == 4].iloc[0]
    assert row4["k_pct_30"] != pytest.approx(baseline_row4["k_pct_30"])


def test_gap_in_calendar_days_does_not_shrink_the_games_based_window():
    # games 2 -> 3 have a 3-calendar-day gap; window is still "games", not "days"
    con = duckdb.connect(":memory:")
    out = team_rolling_features(con, _team_game_stats(), _games())
    row = out[out["game_pk"] == 3].iloc[0]
    assert row["n_games_30"] == 2  # both prior games count, gap or not
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_features_rolling.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bblmlp.features'`.

- [ ] **Step 3: Write the implementation**

Create `src/bblmlp/features/__init__.py` (empty file).

Create `src/bblmlp/features/rolling.py`:

```python
"""As-of trailing rolling-window features over the Statcast-derived rollup
tables (`team_game_stats`, `pitcher_game_stats`).

Every feature for game N is computed only from games strictly before N
(`ROWS BETWEEN N PRECEDING AND 1 PRECEDING`) -- never game N itself. Rates
are reconstructed as sum(numerator)/sum(denominator) over the window, never
a mean of already-computed per-game rates.

At team grain, `xwoba` is a documented approximation: `team_game_stats`
stores a per-game mean over batted-ball events, not a batted-ball count, so
there is no exact denominator to reconstruct against. It is PA-weighted
(`sum(xwoba * pa) / sum(pa)`) as the closest available proxy -- unlike
`k_pct`/`bb_pct`, which reconstruct exactly this way since `k_pct * pa`
recovers the true strikeout count. A precise fix would persist a
batted-ball count in `rollups.py::team_game_stats`; that's a deliberate
fast-follow, not done here.

Cold start (partial windows) is intentionally left as DuckDB computes it
naturally -- fewer rows early, NULL only with zero prior games. Shrinkage
toward a prior is a separate, later concern.
"""
from __future__ import annotations

import duckdb
import pandas as pd

TEAM_WINDOWS: tuple[int, ...] = (30, 162)


def team_rolling_features(
    con: duckdb.DuckDBPyConnection,
    team_game_stats: pd.DataFrame,
    games: pd.DataFrame,
) -> pd.DataFrame:
    window_cols = []
    for w in TEAM_WINDOWS:
        window_cols.append(f"""
            SUM(k_pct * pa) OVER w{w} / NULLIF(SUM(pa) OVER w{w}, 0) AS k_pct_{w},
            SUM(bb_pct * pa) OVER w{w} / NULLIF(SUM(pa) OVER w{w}, 0) AS bb_pct_{w},
            SUM(xwoba * pa) OVER w{w} / NULLIF(SUM(pa) OVER w{w}, 0) AS xwoba_{w},
            COUNT(*) OVER w{w} AS n_games_{w}
        """)
    window_defs = ",\n".join(
        f"w{w} AS (PARTITION BY team ORDER BY game_date, game_datetime, game_pk "
        f"ROWS BETWEEN {w} PRECEDING AND 1 PRECEDING)"
        for w in TEAM_WINDOWS
    )
    sql = f"""
        WITH base AS (
            SELECT t.game_pk, t.season, t.team, t.pa, t.xwoba, t.k_pct, t.bb_pct,
                   g.game_date, g.game_datetime
            FROM team_game_stats_src t
            JOIN games_src g USING (game_pk)
        )
        SELECT game_pk, season, team,
            {",".join(window_cols)}
        FROM base
        WINDOW {window_defs}
        ORDER BY game_date, game_datetime, game_pk
    """
    con.register("team_game_stats_src", team_game_stats)
    con.register("games_src", games)
    try:
        return con.execute(sql).df()
    finally:
        con.unregister("team_game_stats_src")
        con.unregister("games_src")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_features_rolling.py -v`
Expected: PASS — all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/features/ tests/test_features_rolling.py
git commit -m "feat: team-grain rolling-window feature builder"
```

---

## Task 3: `pitcher_rolling_features` builder

**Files:**
- Modify: `src/bblmlp/features/rolling.py`
- Test: `tests/test_features_rolling.py`

**Interfaces:**
- Consumes: nothing from Task 2's function (separate concrete builder, per the design's
  no-shared-engine decision) — but lives in the same module file.
- Produces: `PITCHER_WINDOWS: tuple[int, ...] = (10, 35, 75)` and
  `pitcher_rolling_features(con: duckdb.DuckDBPyConnection, pitcher_game_stats: pd.DataFrame,
  games: pd.DataFrame) -> pd.DataFrame`, returning columns `game_pk, season, pitcher, is_starter,
  k_pct_10, bb_pct_10, swstr_pct_10, avg_velo_10, n_games_10, k_pct_35, bb_pct_35, swstr_pct_35,
  avg_velo_35, n_games_35, k_pct_75, bb_pct_75, swstr_pct_75, avg_velo_75, n_games_75` (exact
  order), ordered by `(game_date, game_datetime, game_pk)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_features_rolling.py`:

```python
from bblmlp.features.rolling import pitcher_rolling_features


def _pitcher_game_stats():
    # One pitcher (id 500), 3 starts.
    return pd.DataFrame({
        "game_pk": [1, 2, 3],
        "season": [2024] * 3,
        "pitcher": [500, 500, 500],
        "is_starter": [True, True, True],
        "pitches": [90, 95, 88],
        "batters_faced": [24, 26, 23],
        "avg_velo": [94.0, 93.5, 94.2],
        "k": [6, 7, 5],
        "bb": [2, 1, 3],
        "whiffs": [10, 12, 9],
    })


def _pitcher_games():
    return pd.DataFrame({
        "game_pk": [1, 2, 3],
        "game_date": ["2024-03-15", "2024-03-20", "2024-03-25"],
        "game_datetime": ["2024-03-15T18:00", "2024-03-20T18:00", "2024-03-25T18:00"],
    })


def test_pitcher_first_start_has_no_history():
    con = duckdb.connect(":memory:")
    out = pitcher_rolling_features(con, _pitcher_game_stats(), _pitcher_games())
    row = out[out["game_pk"] == 1].iloc[0]
    assert row["n_games_10"] == 0
    assert pd.isna(row["k_pct_10"])


def test_pitcher_direct_sum_over_sum_reconstruction():
    con = duckdb.connect(":memory:")
    out = pitcher_rolling_features(con, _pitcher_game_stats(), _pitcher_games())
    row = out[out["game_pk"] == 3].iloc[0]
    # trailing window over starts 1,2
    expected_k_pct = (6 + 7) / (24 + 26)
    expected_swstr = (10 + 12) / (90 + 95)
    assert row["k_pct_10"] == pytest.approx(expected_k_pct)
    assert row["swstr_pct_10"] == pytest.approx(expected_swstr)
    assert row["n_games_10"] == 2


def test_pitcher_avg_velo_is_plain_trailing_mean():
    con = duckdb.connect(":memory:")
    out = pitcher_rolling_features(con, _pitcher_game_stats(), _pitcher_games())
    row = out[out["game_pk"] == 3].iloc[0]
    assert row["avg_velo_10"] == pytest.approx((94.0 + 93.5) / 2)


def test_pitcher_is_starter_passes_through_unwindowed():
    con = duckdb.connect(":memory:")
    out = pitcher_rolling_features(con, _pitcher_game_stats(), _pitcher_games())
    assert out["is_starter"].tolist() == [True, True, True]


def test_pitcher_leakage_perturbing_own_stats_does_not_change_own_row():
    con = duckdb.connect(":memory:")
    baseline = pitcher_rolling_features(con, _pitcher_game_stats(), _pitcher_games())
    baseline_row3 = baseline[baseline["game_pk"] == 3].iloc[0]

    perturbed = _pitcher_game_stats()
    perturbed.loc[perturbed["game_pk"] == 3, "k"] = 99
    con2 = duckdb.connect(":memory:")
    out = pitcher_rolling_features(con2, perturbed, _pitcher_games())
    row3 = out[out["game_pk"] == 3].iloc[0]
    assert row3["k_pct_10"] == pytest.approx(baseline_row3["k_pct_10"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_features_rolling.py -k pitcher -v`
Expected: FAIL with `ImportError: cannot import name 'pitcher_rolling_features'`.

- [ ] **Step 3: Write the implementation**

Append to `src/bblmlp/features/rolling.py`:

```python
PITCHER_WINDOWS: tuple[int, ...] = (10, 35, 75)


def pitcher_rolling_features(
    con: duckdb.DuckDBPyConnection,
    pitcher_game_stats: pd.DataFrame,
    games: pd.DataFrame,
) -> pd.DataFrame:
    window_cols = []
    for w in PITCHER_WINDOWS:
        window_cols.append(f"""
            SUM(k) OVER w{w} / NULLIF(SUM(batters_faced) OVER w{w}, 0) AS k_pct_{w},
            SUM(bb) OVER w{w} / NULLIF(SUM(batters_faced) OVER w{w}, 0) AS bb_pct_{w},
            SUM(whiffs) OVER w{w} / NULLIF(SUM(pitches) OVER w{w}, 0) AS swstr_pct_{w},
            AVG(avg_velo) OVER w{w} AS avg_velo_{w},
            COUNT(*) OVER w{w} AS n_games_{w}
        """)
    window_defs = ",\n".join(
        f"w{w} AS (PARTITION BY pitcher ORDER BY game_date, game_datetime, game_pk "
        f"ROWS BETWEEN {w} PRECEDING AND 1 PRECEDING)"
        for w in PITCHER_WINDOWS
    )
    sql = f"""
        WITH base AS (
            SELECT p.game_pk, p.season, p.pitcher, p.is_starter,
                   p.pitches, p.batters_faced, p.avg_velo, p.k, p.bb, p.whiffs,
                   g.game_date, g.game_datetime
            FROM pitcher_game_stats_src p
            JOIN games_src g USING (game_pk)
        )
        SELECT game_pk, season, pitcher, is_starter,
            {",".join(window_cols)}
        FROM base
        WINDOW {window_defs}
        ORDER BY game_date, game_datetime, game_pk
    """
    con.register("pitcher_game_stats_src", pitcher_game_stats)
    con.register("games_src", games)
    try:
        return con.execute(sql).df()
    finally:
        con.unregister("pitcher_game_stats_src")
        con.unregister("games_src")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_features_rolling.py -v`
Expected: PASS — all tests in the file pass (Task 2's 5 + Task 3's 5 = 10 total).

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/features/rolling.py tests/test_features_rolling.py
git commit -m "feat: pitcher-grain rolling-window feature builder"
```

---

## Task 4: Doubleheader-safe ordering test (both grains)

**Files:**
- Modify: `tests/test_features_rolling.py`

**Interfaces:**
- Consumes: `team_rolling_features` and `pitcher_rolling_features` from Tasks 2/3 (no code
  changes expected — this task proves the shared ordering-key design decision holds for real
  same-day games).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_features_rolling.py`:

```python
def test_team_doubleheader_games_ordered_by_datetime_not_just_date():
    # Two games on the SAME game_date (a doubleheader) -- the earlier
    # game_datetime must be treated as happening first.
    team_game_stats = pd.DataFrame({
        "game_pk": [10, 11, 12],
        "season": [2024] * 3,
        "team": ["NYY"] * 3,
        "pa": [36, 34, 38],
        "xwoba": [0.30, 0.35, 0.28],
        "k_pct": [0.20, 0.30, 0.25],
        "bb_pct": [0.05, 0.06, 0.07],
    })
    games = pd.DataFrame({
        "game_pk": [10, 11, 12],
        "game_date": ["2024-05-01", "2024-05-01", "2024-05-02"],  # 10, 11 = doubleheader
        "game_datetime": ["2024-05-01T13:00", "2024-05-01T19:00", "2024-05-02T18:00"],
    })
    con = duckdb.connect(":memory:")
    out = team_rolling_features(con, team_game_stats, games)

    row_g2 = out[out["game_pk"] == 11].iloc[0]  # game 2 of the doubleheader
    assert row_g2["n_games_30"] == 1
    assert row_g2["k_pct_30"] == pytest.approx(0.20)  # sees only game 10 (the day's opener)

    row_next_day = out[out["game_pk"] == 12].iloc[0]
    assert row_next_day["n_games_30"] == 2  # sees both games 10 and 11


def test_pitcher_doubleheader_starts_ordered_by_datetime_not_just_date():
    pitcher_game_stats = pd.DataFrame({
        "game_pk": [20, 21],
        "season": [2024] * 2,
        "pitcher": [700, 700],
        "is_starter": [True, True],
        "pitches": [90, 85],
        "batters_faced": [24, 22],
        "avg_velo": [93.0, 92.0],
        "k": [5, 6],
        "bb": [2, 1],
        "whiffs": [8, 9],
    })
    games = pd.DataFrame({
        "game_pk": [20, 21],
        "game_date": ["2024-05-01", "2024-05-01"],
        "game_datetime": ["2024-05-01T13:00", "2024-05-01T19:00"],
    })
    con = duckdb.connect(":memory:")
    out = pitcher_rolling_features(con, pitcher_game_stats, games)
    row_g2 = out[out["game_pk"] == 21].iloc[0]
    assert row_g2["n_games_10"] == 1
    assert row_g2["k_pct_10"] == pytest.approx(5 / 24)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_features_rolling.py -k doubleheader -v`
Expected: PASS immediately — this task verifies Tasks 2/3's `ORDER BY game_date, game_datetime,
game_pk` is already doubleheader-safe; it is not introducing new behavior. If either test FAILS,
the ordering key in Task 2 or 3's SQL is wrong and must be fixed before proceeding (do not change
the test to match broken behavior).

- [ ] **Step 3: Run the full feature-test file to confirm no regressions**

Run: `uv run --no-sync pytest tests/test_features_rolling.py -v`
Expected: PASS — all tests in the file pass (12 total).

- [ ] **Step 4: Commit**

```bash
git add tests/test_features_rolling.py
git commit -m "test: verify doubleheader-safe ordering for both feature grains"
```

---

## Task 5: `bblmlp build features` CLI command

**Files:**
- Modify: `src/bblmlp/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `team_rolling_features`, `pitcher_rolling_features` from `bblmlp.features.rolling`
  (Tasks 2/3); `replace_partition` from `bblmlp.storage` (existing); `team_features`/
  `pitcher_features` tables from Task 1.
- Produces: `bblmlp build features --season <year>` CLI command, registered under the existing
  `build_app` Typer sub-app.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_build_group_has_features_command():
    result = runner.invoke(app, ["build", "--help"])
    assert result.exit_code == 0
    assert "features" in result.stdout


def test_build_features_writes_team_and_pitcher_rows(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from bblmlp.storage import connect, init_schema, replace_partition

    warehouse = tmp_path / "w.duckdb"
    con = connect(warehouse)
    init_schema(con)

    con.execute("INSERT INTO games (game_pk, season, game_date, game_datetime, home_team, away_team) VALUES "
                "(1, 2024, '2024-03-15', '2024-03-15T18:00', 'NYY', 'BOS'), "
                "(2, 2024, '2024-03-16', '2024-03-16T18:00', 'NYY', 'BOS')")

    import pandas as pd
    replace_partition(con, "team_game_stats", pd.DataFrame({
        "game_pk": [1, 2], "season": [2024, 2024], "team": ["NYY", "NYY"],
        "pa": [36, 41], "xwoba": [0.30, 0.25], "k_pct": [0.25, 0.17], "bb_pct": [0.05, 0.02],
    }), "season")
    replace_partition(con, "pitcher_game_stats", pd.DataFrame({
        "game_pk": [1, 2], "season": [2024, 2024], "pitcher": [500, 500],
        "pitches": [90, 95], "batters_faced": [24, 26], "avg_velo": [94.0, 93.5],
        "xwoba_against": [0.28, 0.30], "k": [6, 7], "bb": [2, 1], "whiffs": [10, 12],
        "swstr_pct": [0.11, 0.13], "is_starter": [True, True],
    }), "season")
    con.close()

    fake_settings = SimpleNamespace(data=SimpleNamespace(warehouse_path=warehouse))
    monkeypatch.setattr("bblmlp.config.load_settings", lambda *a, **k: fake_settings)

    result = runner.invoke(app, ["build", "features", "--season", "2024"])
    assert result.exit_code == 0

    con = connect(warehouse)
    assert con.execute("SELECT COUNT(*) FROM team_features").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM pitcher_features").fetchone()[0] == 2
    con.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_cli.py -k features -v`
Expected: FAIL — `"features" in result.stdout` is False (command doesn't exist yet).

- [ ] **Step 3: Write the implementation**

In `src/bblmlp/cli.py`, add after the existing `build_park_reference_cmd` function (following the
exact same pattern — see lines ~254-289 for `build_rollups`/`build_park_reference`):

```python
@build_app.command("features")
def build_features_cmd(season: int = typer.Option(..., "--season")) -> None:
    """Compute as-of rolling-window features (team + pitcher grain) for a season."""
    from bblmlp.config import load_settings
    from bblmlp.features.rolling import pitcher_rolling_features, team_rolling_features
    from bblmlp.storage import connect, init_schema, replace_partition

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    games = con.execute(
        "SELECT game_pk, game_date, game_datetime FROM games WHERE season = ?", [season]
    ).df()
    team_game_stats = con.execute(
        "SELECT * FROM team_game_stats WHERE season = ?", [season]
    ).df()
    pitcher_game_stats = con.execute(
        "SELECT * FROM pitcher_game_stats WHERE season = ?", [season]
    ).df()
    team_rows = replace_partition(
        con, "team_features", team_rolling_features(con, team_game_stats, games), "season"
    )
    pitcher_rows = replace_partition(
        con, "pitcher_features", pitcher_rolling_features(con, pitcher_game_stats, games), "season"
    )
    con.close()
    typer.echo(f"Wrote {team_rows} team-feature rows and {pitcher_rows} pitcher-feature rows for {season}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_cli.py -v`
Expected: PASS — all `test_cli.py` tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/cli.py tests/test_cli.py
git commit -m "feat: bblmlp build features CLI command"
```

---

## Task 6: Full suite + docs pass

**Files:**
- Modify: `CLAUDE.md` (Commands section + "Not yet built" status paragraph)

**Interfaces:** None — documentation-only task, closing the loop on CLAUDE.md accuracy per the
repo's own workflow conventions.

- [ ] **Step 1: Run the full suite**

Run: `uv run --no-sync pytest -q`
Expected: PASS — all tests green (72 existing + new tests from Tasks 1-5).

- [ ] **Step 2: Update CLAUDE.md's Commands section**

Add this line after `uv run bblmlp build rollups --season 2024     # ...` in the Commands code
block:

```
uv run bblmlp build features --season 2024    # as-of rolling-window team/pitcher features
```

- [ ] **Step 3: Update CLAUDE.md's Current status section**

In the "Not yet built" paragraph, change:

```
**Not yet built** (next work, per the design doc): feature engineering (`features/`), the game-winner
model (`models/game/` — Elo baseline → LightGBM + isotonic calibration), Kalshi ingestion
(`ingest/kalshi/`), the bet crafter (`betting/`), and backtest (`backtest/`).
```

to:

```
**Not yet built** (next work, per the design doc): the rest of `features/` beyond the rolling-window
builder (bullpen features, cold-start/shrinkage, batter/lineup features — roadmap #5-#7), the
game-winner model (`models/game/` — Elo baseline → LightGBM + isotonic calibration), the bet
crafter (`betting/`), and backtest (`backtest/`). Kalshi ingestion (`ingest/kalshi/`) is built on
a feature branch, not yet merged to `main`.
```

(Adjust the Kalshi clause only if it has since merged — check `git log main -- src/bblmlp/ingest/kalshi/` first; if it's already on `main`, drop that sentence instead of adding it.)

- [ ] **Step 4: Verify the full suite one more time**

Run: `uv run --no-sync pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: reflect rolling-window feature builder in CLAUDE.md"
```
