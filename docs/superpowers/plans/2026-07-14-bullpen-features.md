# Bullpen Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add team-level bullpen strength as an as-of, exact (never starter-subtracted) rolling-window
feature at 10/35/75-game windows, joinable onto `games` the same way `team_features`/`pitcher_features`
already are.

**Architecture:** `pitcher_game_stats` gains a `team` column (previously computed internally, never
persisted). A new rollup, `bullpen_game_stats`, aggregates `pitcher_game_stats` rows where
`is_starter == False`, grouped by `(game_pk, team)` — exact summed counts, no subtraction logic. A new
windowed builder, `features/bullpen.py::bullpen_rolling_features`, applies the same DuckDB
window-function machinery as `features/rolling.py`, partitioned by `team` instead of `pitcher`.

**Tech Stack:** Python, pandas, DuckDB (window functions), Typer CLI, pytest.

## Global Constraints

- No network calls anywhere in this work — every function operates on DataFrames already in the
  warehouse or passed in as fixtures (spec §2-§4).
- Bullpen aggregation must be **exact** (summed raw counts from `is_starter == False` rows), never
  derived by subtracting starter totals from team totals (spec §1, §3).
- Rates are `sum(numerator)/sum(denominator)` over the window, never a mean of per-game rates (spec §4,
  consistent with #4's rolling-window design doc).
- Ordering key is always `(game_date, game_datetime, game_pk)` — the doubleheader disambiguator
  established in #4 (spec §4).
- Run tests with `uv run --no-sync pytest -q`, not a bare `pytest` (CLAUDE.md gotcha).
- All new tests must pass and the existing suite (110 tests as of this plan) must stay green (spec §8).

---

## File Structure

- **Modify** `src/bblmlp/storage/warehouse.py` — add `team VARCHAR` to `PITCHER_GAME_DDL`; add new
  `BULLPEN_GAME_DDL` and `BULLPEN_FEATURES_DDL`; wire both into `init_schema`.
- **Modify** `src/bblmlp/ingest/mlb/rollups.py` — `pitcher_game_stats` persists `team`; new
  `bullpen_game_stats` function.
- **Create** `src/bblmlp/features/bullpen.py` — `bullpen_rolling_features`, mirroring
  `features/rolling.py::pitcher_rolling_features` but partitioned by `team`.
- **Modify** `src/bblmlp/cli.py` — `build_rollups` writes `bullpen_game_stats`; `build_features_cmd`
  writes `bullpen_features`.
- **Modify** `tests/test_rollups.py` — team-column test, bullpen aggregation tests.
- **Create** `tests/test_features_bullpen.py` — windowing tests, mirroring
  `tests/test_features_rolling.py`'s pitcher-grain tests.
- **Modify** `tests/test_warehouse.py` — DDL column-list tests for the two new/changed tables.
- **Modify** `tests/test_cli.py` — CLI wiring tests for both commands.
- **Modify** `docs/cli-usage.md`, `CLAUDE.md` — document the new table/CLI surface.

---

### Task 1: `pitcher_game_stats` persists a `team` column

**Files:**
- Modify: `src/bblmlp/storage/warehouse.py:114-129` (`PITCHER_GAME_DDL`)
- Modify: `src/bblmlp/ingest/mlb/rollups.py:21-47` (`pitcher_game_stats`)
- Test: `tests/test_rollups.py`, `tests/test_warehouse.py`

**Interfaces:**
- Produces: `pitcher_game_stats(pitches: pd.DataFrame) -> pd.DataFrame` now includes a `team` column
  (Statcast abbreviation of the pitcher's fielding side that game) in its output, in addition to all
  existing columns. Column order: `game_pk, pitcher, season, team, pitches, batters_faced, avg_velo,
  xwoba_against, k, bb, whiffs, swstr_pct, is_starter`.

- [ ] **Step 1: Write the failing test for the `team` column**

Add to `tests/test_rollups.py`:

```python
def test_pitcher_game_stats_includes_fielding_team():
    out = pitcher_game_stats(_pitches())
    # pitcher 500 fields for SF (throws in Top1, i.e. the home/fielding side when away bats)
    # pitcher 900 fields for COL (throws in Bot1)
    row_500 = out[out["pitcher"] == 500].iloc[0]
    row_900 = out[out["pitcher"] == 900].iloc[0]
    assert row_500["team"] == "SF"
    assert row_900["team"] == "COL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_rollups.py::test_pitcher_game_stats_includes_fielding_team -v`
Expected: FAIL with `KeyError: 'team'`

- [ ] **Step 3: Add `team` to the DDL**

In `src/bblmlp/storage/warehouse.py`, change `PITCHER_GAME_DDL` from:

```python
PITCHER_GAME_DDL = """
CREATE TABLE IF NOT EXISTS pitcher_game_stats (
    game_pk BIGINT,
    pitcher INTEGER,
    season INTEGER,
    pitches INTEGER,
```

to:

```python
PITCHER_GAME_DDL = """
CREATE TABLE IF NOT EXISTS pitcher_game_stats (
    game_pk BIGINT,
    pitcher INTEGER,
    season INTEGER,
    team VARCHAR,
    pitches INTEGER,
```

(rest of the DDL unchanged).

- [ ] **Step 4: Persist `team` in `pitcher_game_stats`**

In `src/bblmlp/ingest/mlb/rollups.py`, change:

```python
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
```

to:

```python
def pitcher_game_stats(pitches: pd.DataFrame) -> pd.DataFrame:
    df = pitches.copy()
    df["fld_team"] = _fielding_team(df)
    g = df.groupby(["game_pk", "season", "pitcher"], as_index=False)
    out = g.agg(
        team=("fld_team", "first"),
        pitches=("pitch_number", "size"),
        batters_faced=("at_bat_number", "nunique"),
        avg_velo=("release_speed", "mean"),
        xwoba_against=("estimated_woba_using_speedangle", "mean"),
    )
```

(`fld_team` is constant within each `(game_pk, pitcher)` group — every pitch a pitcher throws in one
game is on the same fielding side — so `"first"` is exact, not an approximation. The rest of the
function, including the `first_ab`/`starters` logic below it, is unchanged.)

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_rollups.py::test_pitcher_game_stats_includes_fielding_team -v`
Expected: PASS

- [ ] **Step 6: Add a DDL column-order test**

Add to `tests/test_warehouse.py`:

```python
def test_init_schema_pitcher_game_stats_has_team_column(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    cols = [r[0] for r in con.execute("DESCRIBE pitcher_game_stats").fetchall()]
    assert cols == [
        "game_pk", "pitcher", "season", "team", "pitches", "batters_faced",
        "avg_velo", "xwoba_against", "k", "bb", "whiffs", "swstr_pct", "is_starter",
    ]
```

- [ ] **Step 7: Run the full test file to verify no regressions**

Run: `uv run --no-sync pytest tests/test_rollups.py tests/test_warehouse.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/bblmlp/storage/warehouse.py src/bblmlp/ingest/mlb/rollups.py tests/test_rollups.py tests/test_warehouse.py
git commit -m "feat: persist fielding team on pitcher_game_stats"
```

---

### Task 2: `bullpen_game_stats` — exact per-game bullpen aggregation

**Files:**
- Modify: `src/bblmlp/storage/warehouse.py` (new `BULLPEN_GAME_DDL`, wire into `init_schema`)
- Modify: `src/bblmlp/ingest/mlb/rollups.py` (new `bullpen_game_stats` function)
- Test: `tests/test_rollups.py`, `tests/test_warehouse.py`

**Interfaces:**
- Consumes: the `team`-augmented output of `pitcher_game_stats` from Task 1 (columns: `game_pk,
  pitcher, season, team, pitches, batters_faced, avg_velo, xwoba_against, k, bb, whiffs, swstr_pct,
  is_starter`).
- Produces: `bullpen_game_stats(pitcher_game_stats: pd.DataFrame) -> pd.DataFrame`, one row per
  `(game_pk, team)`, columns: `game_pk, season, team, pitches, batters_faced, k, bb, whiffs,
  n_pitchers, avg_velo, swstr_pct`. Later tasks (Task 3, Task 4) rely on exactly these column names.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_rollups.py`:

```python
from bblmlp.ingest.mlb.rollups import bullpen_game_stats


def _pitcher_game_stats_for_bullpen():
    # One game (game_pk=1), SF's staff: one starter (501) + two relievers (502, 503).
    return pd.DataFrame({
        "game_pk": [1, 1, 1],
        "season": [2024] * 3,
        "pitcher": [501, 502, 503],
        "team": ["SF", "SF", "SF"],
        "pitches": [90, 20, 15],
        "batters_faced": [24, 6, 4],
        "avg_velo": [94.0, 96.0, 92.0],
        "xwoba_against": [0.28, 0.20, 0.35],
        "k": [6, 2, 1],
        "bb": [2, 0, 1],
        "whiffs": [10, 4, 2],
        "swstr_pct": [10 / 90, 4 / 20, 2 / 15],
        "is_starter": [True, False, False],
    })


def test_bullpen_game_stats_excludes_the_starter():
    out = bullpen_game_stats(_pitcher_game_stats_for_bullpen())
    row = out[(out["game_pk"] == 1) & (out["team"] == "SF")].iloc[0]
    assert row["pitches"] == 35       # 20 + 15, starter's 90 excluded
    assert row["batters_faced"] == 10  # 6 + 4
    assert row["k"] == 3               # 2 + 1
    assert row["bb"] == 1              # 0 + 1
    assert row["whiffs"] == 6          # 4 + 2


def test_bullpen_game_stats_n_pitchers_counts_distinct_relievers():
    out = bullpen_game_stats(_pitcher_game_stats_for_bullpen())
    row = out[(out["game_pk"] == 1) & (out["team"] == "SF")].iloc[0]
    assert row["n_pitchers"] == 2


def test_bullpen_game_stats_swstr_pct_is_exact_sum_reconstruction():
    out = bullpen_game_stats(_pitcher_game_stats_for_bullpen())
    row = out[(out["game_pk"] == 1) & (out["team"] == "SF")].iloc[0]
    assert row["swstr_pct"] == pytest.approx(6 / 35)  # sum(whiffs)/sum(pitches), not mean of rates


def test_bullpen_game_stats_avg_velo_is_pitch_weighted():
    out = bullpen_game_stats(_pitcher_game_stats_for_bullpen())
    row = out[(out["game_pk"] == 1) & (out["team"] == "SF")].iloc[0]
    expected = (96.0 * 20 + 92.0 * 15) / (20 + 15)
    assert row["avg_velo"] == pytest.approx(expected)
```

(add `import pytest` at the top of `tests/test_rollups.py` if not already present)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_rollups.py -k bullpen -v`
Expected: FAIL with `ImportError: cannot import name 'bullpen_game_stats'`

- [ ] **Step 3: Add the DDL**

In `src/bblmlp/storage/warehouse.py`, add after `TEAM_GAME_DDL` (before `STANDINGS_DDL`):

```python
BULLPEN_GAME_DDL = """
CREATE TABLE IF NOT EXISTS bullpen_game_stats (
    game_pk BIGINT,
    season INTEGER,
    team VARCHAR,
    pitches INTEGER,
    batters_faced INTEGER,
    k INTEGER,
    bb INTEGER,
    whiffs INTEGER,
    n_pitchers INTEGER,
    avg_velo DOUBLE,
    swstr_pct DOUBLE
);
"""
```

Then add `con.execute(BULLPEN_GAME_DDL)` to `init_schema`, right after `con.execute(TEAM_GAME_DDL)`:

```python
def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(GAMES_DDL)
    con.execute(STATCAST_DDL)
    con.execute(PLAYER_IDS_DDL)
    con.execute(PITCHER_GAME_DDL)
    con.execute(TEAM_GAME_DDL)
    con.execute(BULLPEN_GAME_DDL)
    con.execute(STANDINGS_DDL)
    ...
```

- [ ] **Step 4: Implement `bullpen_game_stats`**

In `src/bblmlp/ingest/mlb/rollups.py`, add after `pitcher_game_stats`:

```python
def bullpen_game_stats(pitcher_game_stats: pd.DataFrame) -> pd.DataFrame:
    """Exact per-game bullpen aggregation -- summed raw counts from relief
    appearances (`is_starter == False`), never a subtraction of starter
    totals from team totals. `avg_velo` is a pitch-weighted mean of each
    reliever's own (already-averaged) `avg_velo`, the same documented
    approximation pattern as team-grain `xwoba` in `features/rolling.py`.
    """
    df = pitcher_game_stats[~pitcher_game_stats["is_starter"]].copy()
    g = df.groupby(["game_pk", "season", "team"], as_index=False)
    out = g.agg(
        pitches=("pitches", "sum"),
        batters_faced=("batters_faced", "sum"),
        k=("k", "sum"),
        bb=("bb", "sum"),
        whiffs=("whiffs", "sum"),
        n_pitchers=("pitcher", "nunique"),
    )
    weighted_velo = (
        df.assign(_w=df["avg_velo"] * df["pitches"])
        .groupby(["game_pk", "season", "team"])["_w"]
        .sum()
    )
    out = out.set_index(["game_pk", "season", "team"])
    out["avg_velo"] = weighted_velo / out["pitches"]
    out["swstr_pct"] = out["whiffs"] / out["pitches"]
    return out.reset_index()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_rollups.py -k bullpen -v`
Expected: All PASS

- [ ] **Step 6: Add a DDL column-order test**

Add to `tests/test_warehouse.py`:

```python
def test_init_schema_creates_bullpen_game_stats_table(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    assert "bullpen_game_stats" in table_names(con)
    cols = [r[0] for r in con.execute("DESCRIBE bullpen_game_stats").fetchall()]
    assert cols == [
        "game_pk", "season", "team", "pitches", "batters_faced",
        "k", "bb", "whiffs", "n_pitchers", "avg_velo", "swstr_pct",
    ]
```

- [ ] **Step 7: Run the full test file to verify no regressions**

Run: `uv run --no-sync pytest tests/test_rollups.py tests/test_warehouse.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/bblmlp/storage/warehouse.py src/bblmlp/ingest/mlb/rollups.py tests/test_rollups.py tests/test_warehouse.py
git commit -m "feat: bullpen_game_stats exact per-game aggregation"
```

---

### Task 3: Wire `bullpen_game_stats` into `bblmlp build rollups`

**Files:**
- Modify: `src/bblmlp/cli.py:269-285` (`build_rollups`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `bullpen_game_stats` from Task 2 (`src/bblmlp/ingest/mlb/rollups.py`).

- [ ] **Step 1: Write the failing CLI test**

Add to `tests/test_cli.py`:

```python
def test_build_rollups_writes_bullpen_game_stats(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from bblmlp.storage import connect, init_schema, replace_partition

    warehouse = tmp_path / "w.duckdb"
    con = connect(warehouse)
    init_schema(con)

    import pandas as pd
    # One game, one team, one starter + one reliever, minimal statcast_pitches fixture.
    # All rows are "Top" half-innings: SF (home) fields/pitches, COL (away) bats -- so
    # both pitcher 501 (inning 1) and pitcher 502 (inning 8) resolve to team "SF" per
    # _fielding_team's Top-half = home_team rule. A "Bot" row here would put pitcher 502
    # on COL instead, since _fielding_team flips to away_team in the bottom half.
    pitches = pd.DataFrame({
        "game_pk": [1, 1, 1, 1],
        "season": [2024] * 4,
        "inning": [1, 1, 8, 8],
        "inning_topbot": ["Top", "Top", "Top", "Top"],
        "home_team": ["SF"] * 4, "away_team": ["COL"] * 4,
        "pitcher": [501, 501, 502, 502],
        "batter": [10, 11, 12, 13],
        "at_bat_number": [1, 2, 20, 21],
        "pitch_number": [1, 1, 1, 1],
        "events": ["strikeout", "walk", "strikeout", "field_out"],
        "description": ["swinging_strike", "ball", "swinging_strike", "hit_into_play"],
        "estimated_woba_using_speedangle": [0.0, 0.0, 0.0, 0.1],
        "release_speed": [95, 96, 97, 96],
    })
    replace_partition(con, "statcast_pitches", pitches, "season")
    con.close()

    fake_settings = SimpleNamespace(data=SimpleNamespace(warehouse_path=warehouse))
    monkeypatch.setattr("bblmlp.config.load_settings", lambda *a, **k: fake_settings)

    result = runner.invoke(app, ["build", "rollups", "--season", "2024"])
    assert result.exit_code == 0

    con = connect(warehouse)
    row = con.execute("SELECT * FROM bullpen_game_stats WHERE game_pk = 1").df().iloc[0]
    assert row["team"] == "SF"
    assert row["n_pitchers"] == 1  # only pitcher 502 is a reliever (501 is the starter)
    con.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_cli.py::test_build_rollups_writes_bullpen_game_stats -v`
Expected: FAIL — `bullpen_game_stats` table has 0 rows or doesn't get written (CLI doesn't call the
new function yet)

- [ ] **Step 3: Wire it into `build_rollups`**

In `src/bblmlp/cli.py`, change:

```python
@build_app.command("rollups")
def build_rollups(season: int = typer.Option(..., "--season")) -> None:
    """Compute Statcast-derived pitcher/team game rollups for a season."""
    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.rollups import pitcher_game_stats, team_game_stats
    from bblmlp.storage import connect, init_schema, replace_partition

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    pitches = con.execute(
        "SELECT * FROM statcast_pitches WHERE season = ?", [season]
    ).df()
    pitcher_rows = replace_partition(con, "pitcher_game_stats", pitcher_game_stats(pitches), "season")
    team_rows = replace_partition(con, "team_game_stats", team_game_stats(pitches), "season")
    con.close()
    typer.echo(f"Wrote {pitcher_rows} pitcher-game rows and {team_rows} team-game rows for {season}")
```

to:

```python
@build_app.command("rollups")
def build_rollups(season: int = typer.Option(..., "--season")) -> None:
    """Compute Statcast-derived pitcher/team/bullpen game rollups for a season."""
    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.rollups import bullpen_game_stats, pitcher_game_stats, team_game_stats
    from bblmlp.storage import connect, init_schema, replace_partition

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    pitches = con.execute(
        "SELECT * FROM statcast_pitches WHERE season = ?", [season]
    ).df()
    pitcher_game_stats_df = pitcher_game_stats(pitches)
    pitcher_rows = replace_partition(con, "pitcher_game_stats", pitcher_game_stats_df, "season")
    team_rows = replace_partition(con, "team_game_stats", team_game_stats(pitches), "season")
    bullpen_rows = replace_partition(
        con, "bullpen_game_stats", bullpen_game_stats(pitcher_game_stats_df), "season"
    )
    con.close()
    typer.echo(
        f"Wrote {pitcher_rows} pitcher-game rows, {team_rows} team-game rows, "
        f"and {bullpen_rows} bullpen-game rows for {season}"
    )
```

(`bullpen_game_stats` is computed from the in-memory `pitcher_game_stats_df`, not re-read from the
warehouse — same frame that was just written.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_cli.py::test_build_rollups_writes_bullpen_game_stats -v`
Expected: PASS

- [ ] **Step 5: Run the full test file to verify no regressions**

Run: `uv run --no-sync pytest tests/test_cli.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/bblmlp/cli.py tests/test_cli.py
git commit -m "feat: bblmlp build rollups writes bullpen_game_stats"
```

---

### Task 4: `bullpen_features` — windowed bullpen output

**Files:**
- Create: `src/bblmlp/features/bullpen.py`
- Modify: `src/bblmlp/storage/warehouse.py` (new `BULLPEN_FEATURES_DDL`, wire into `init_schema`)
- Test: `tests/test_features_bullpen.py`, `tests/test_warehouse.py`

**Interfaces:**
- Consumes: `bullpen_game_stats` output from Task 2 (columns: `game_pk, season, team, pitches,
  batters_faced, k, bb, whiffs, n_pitchers, avg_velo, swstr_pct`); `games` narrowed to `game_pk,
  game_date, game_datetime` (same contract as `features/rolling.py`'s builders).
- Produces: `bullpen_rolling_features(con, bullpen_game_stats: pd.DataFrame, games: pd.DataFrame) ->
  pd.DataFrame`, one row per `(game_pk, team)`, columns: `game_pk, season, team,
  k_pct_10/35/75, bb_pct_10/35/75, swstr_pct_10/35/75, avg_velo_10/35/75, n_games_10/35/75`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_features_bullpen.py`:

```python
import duckdb
import pandas as pd
import pytest

from bblmlp.features.bullpen import bullpen_rolling_features


def _bullpen_game_stats():
    # One team (SF), 3 consecutive bullpen-games.
    return pd.DataFrame({
        "game_pk": [1, 2, 3],
        "season": [2024] * 3,
        "team": ["SF"] * 3,
        "pitches": [35, 40, 30],
        "batters_faced": [10, 11, 9],
        "k": [3, 4, 2],
        "bb": [1, 2, 1],
        "whiffs": [6, 7, 5],
        "n_pitchers": [2, 3, 2],
        "avg_velo": [94.3, 95.1, 93.8],
        "swstr_pct": [6 / 35, 7 / 40, 5 / 30],
    })


def _games():
    return pd.DataFrame({
        "game_pk": [1, 2, 3],
        "game_date": ["2024-03-15", "2024-03-16", "2024-03-17"],
        "game_datetime": ["2024-03-15T18:00", "2024-03-16T18:00", "2024-03-17T18:00"],
    })


def test_bullpen_first_game_has_no_history():
    con = duckdb.connect(":memory:")
    out = bullpen_rolling_features(con, _bullpen_game_stats(), _games())
    row = out[out["game_pk"] == 1].iloc[0]
    assert row["n_games_10"] == 0
    assert pd.isna(row["k_pct_10"])


def test_bullpen_direct_sum_over_sum_reconstruction():
    con = duckdb.connect(":memory:")
    out = bullpen_rolling_features(con, _bullpen_game_stats(), _games())
    row = out[out["game_pk"] == 3].iloc[0]
    # trailing window over games 1, 2
    expected_k_pct = (3 + 4) / (10 + 11)
    expected_swstr = (6 + 7) / (35 + 40)
    assert row["k_pct_10"] == pytest.approx(expected_k_pct)
    assert row["swstr_pct_10"] == pytest.approx(expected_swstr)
    assert row["n_games_10"] == 2


def test_bullpen_avg_velo_is_plain_trailing_mean():
    con = duckdb.connect(":memory:")
    out = bullpen_rolling_features(con, _bullpen_game_stats(), _games())
    row = out[out["game_pk"] == 3].iloc[0]
    assert row["avg_velo_10"] == pytest.approx((94.3 + 95.1) / 2)


def test_bullpen_leakage_perturbing_own_stats_does_not_change_own_row():
    con = duckdb.connect(":memory:")
    baseline = bullpen_rolling_features(con, _bullpen_game_stats(), _games())
    baseline_row3 = baseline[baseline["game_pk"] == 3].iloc[0]

    perturbed = _bullpen_game_stats()
    perturbed.loc[perturbed["game_pk"] == 3, "k"] = 99
    con2 = duckdb.connect(":memory:")
    out = bullpen_rolling_features(con2, perturbed, _games())
    row3 = out[out["game_pk"] == 3].iloc[0]
    assert row3["k_pct_10"] == pytest.approx(baseline_row3["k_pct_10"])


def test_bullpen_doubleheader_games_ordered_by_datetime_not_just_date():
    # pk 20 is the nightcap (19:00), pk 21 is the opener (13:00) -- deliberately
    # inverted game_pk order so a game_datetime-dropping regression would fail this.
    bullpen_game_stats = pd.DataFrame({
        "game_pk": [21, 20],
        "season": [2024] * 2,
        "team": ["SF"] * 2,
        "pitches": [35, 40],
        "batters_faced": [10, 11],
        "k": [3, 4],
        "bb": [1, 2],
        "whiffs": [6, 7],
        "n_pitchers": [2, 3],
        "avg_velo": [94.3, 95.1],
        "swstr_pct": [6 / 35, 7 / 40],
    })
    games = pd.DataFrame({
        "game_pk": [21, 20],
        "game_date": ["2024-05-01", "2024-05-01"],
        "game_datetime": ["2024-05-01T13:00", "2024-05-01T19:00"],
    })
    con = duckdb.connect(":memory:")
    out = bullpen_rolling_features(con, bullpen_game_stats, games)

    row_nightcap = out[out["game_pk"] == 20].iloc[0]
    assert row_nightcap["n_games_10"] == 1
    assert row_nightcap["k_pct_10"] == pytest.approx(3 / 10)  # sees only pk 21 (the opener)

    row_opener = out[out["game_pk"] == 21].iloc[0]
    assert row_opener["n_games_10"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_features_bullpen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bblmlp.features.bullpen'`

- [ ] **Step 3: Add the DDL**

In `src/bblmlp/storage/warehouse.py`, add after `PITCHER_FEATURES_DDL` (before `KALSHI_QUOTES_DDL`):

```python
BULLPEN_FEATURES_DDL = """
CREATE TABLE IF NOT EXISTS bullpen_features (
    game_pk BIGINT,
    season INTEGER,
    team VARCHAR,
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

Then add `con.execute(BULLPEN_FEATURES_DDL)` to `init_schema`, right after
`con.execute(PITCHER_FEATURES_DDL)`:

```python
    con.execute(PARK_REFERENCE_DDL)
    con.execute(TEAM_FEATURES_DDL)
    con.execute(PITCHER_FEATURES_DDL)
    con.execute(BULLPEN_FEATURES_DDL)
    con.execute(KALSHI_QUOTES_DDL)
```

- [ ] **Step 4: Implement `bullpen_rolling_features`**

Create `src/bblmlp/features/bullpen.py`:

```python
"""As-of trailing rolling-window bullpen features, partitioned by team
rather than individual pitcher identity -- a team's bullpen is a rotating
cast of relievers, not one pitcher's own trailing form (contrast
`features/rolling.py::pitcher_rolling_features`, which windows by pitcher
identity). Built on top of `bullpen_game_stats`
(`ingest/mlb/rollups.py`), itself an exact -- never starter-subtracted --
per-game aggregation of `pitcher_game_stats` rows where `is_starter ==
False`.

Same leakage guard and rate-reconstruction convention as
`features/rolling.py`: every feature for game N is computed only from
games strictly before N (`ROWS BETWEEN N PRECEDING AND 1 PRECEDING`), and
rates are sum(numerator)/sum(denominator) over the window, never a mean of
per-game rates.
"""
from __future__ import annotations

import duckdb
import pandas as pd

BULLPEN_WINDOWS: tuple[int, ...] = (10, 35, 75)


def bullpen_rolling_features(
    con: duckdb.DuckDBPyConnection,
    bullpen_game_stats: pd.DataFrame,
    games: pd.DataFrame,
) -> pd.DataFrame:
    window_cols = []
    for w in BULLPEN_WINDOWS:
        window_cols.append(f"""
            SUM(k) OVER w{w} / NULLIF(SUM(batters_faced) OVER w{w}, 0) AS k_pct_{w},
            SUM(bb) OVER w{w} / NULLIF(SUM(batters_faced) OVER w{w}, 0) AS bb_pct_{w},
            SUM(whiffs) OVER w{w} / NULLIF(SUM(pitches) OVER w{w}, 0) AS swstr_pct_{w},
            AVG(avg_velo) OVER w{w} AS avg_velo_{w},
            COUNT(*) OVER w{w} AS n_games_{w}
        """)
    window_defs = ",\n".join(
        f"w{w} AS (PARTITION BY team ORDER BY game_date, game_datetime, game_pk "
        f"ROWS BETWEEN {w} PRECEDING AND 1 PRECEDING)"
        for w in BULLPEN_WINDOWS
    )
    sql = f"""
        WITH base AS (
            SELECT b.game_pk, b.season, b.team,
                   b.pitches, b.batters_faced, b.k, b.bb, b.whiffs, b.avg_velo,
                   g.game_date, g.game_datetime
            FROM bullpen_game_stats_src b
            JOIN games_src g USING (game_pk)
        )
        SELECT game_pk, season, team,
            {",".join(window_cols)}
        FROM base
        WINDOW {window_defs}
        ORDER BY game_date, game_datetime, game_pk
    """
    con.register("bullpen_game_stats_src", bullpen_game_stats)
    con.register("games_src", games)
    try:
        return con.execute(sql).df()
    finally:
        con.unregister("bullpen_game_stats_src")
        con.unregister("games_src")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_features_bullpen.py -v`
Expected: All PASS

- [ ] **Step 6: Add a DDL test**

Add to `tests/test_warehouse.py`:

```python
def test_init_schema_creates_bullpen_features_table(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    assert "bullpen_features" in table_names(con)
    cols = [r[0] for r in con.execute("DESCRIBE bullpen_features").fetchall()]
    assert cols == [
        "game_pk", "season", "team",
        "k_pct_10", "bb_pct_10", "swstr_pct_10", "avg_velo_10", "n_games_10",
        "k_pct_35", "bb_pct_35", "swstr_pct_35", "avg_velo_35", "n_games_35",
        "k_pct_75", "bb_pct_75", "swstr_pct_75", "avg_velo_75", "n_games_75",
    ]
```

- [ ] **Step 7: Run the full test file to verify no regressions**

Run: `uv run --no-sync pytest tests/test_features_bullpen.py tests/test_warehouse.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/bblmlp/features/bullpen.py src/bblmlp/storage/warehouse.py tests/test_features_bullpen.py tests/test_warehouse.py
git commit -m "feat: pitcher-grain bullpen rolling-window feature builder"
```

---

### Task 5: Wire `bullpen_features` into `bblmlp build features`

**Files:**
- Modify: `src/bblmlp/cli.py:305-340` (`build_features_cmd`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `bullpen_rolling_features` from Task 4 (`src/bblmlp/features/bullpen.py`).

- [ ] **Step 1: Write the failing CLI test**

Add to `tests/test_cli.py`:

```python
def test_build_features_writes_bullpen_rows(tmp_path, monkeypatch):
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
        "game_pk": [1, 2], "season": [2024, 2024], "pitcher": [500, 500], "team": ["NYY", "NYY"],
        "pitches": [90, 95], "batters_faced": [24, 26], "avg_velo": [94.0, 93.5],
        "xwoba_against": [0.28, 0.30], "k": [6, 7], "bb": [2, 1], "whiffs": [10, 12],
        "swstr_pct": [0.11, 0.13], "is_starter": [True, True],
    }), "season")
    replace_partition(con, "bullpen_game_stats", pd.DataFrame({
        "game_pk": [1, 2], "season": [2024, 2024], "team": ["NYY", "NYY"],
        "pitches": [35, 40], "batters_faced": [10, 11], "k": [3, 4], "bb": [1, 2],
        "whiffs": [6, 7], "n_pitchers": [2, 3], "avg_velo": [94.3, 95.1],
        "swstr_pct": [6 / 35, 7 / 40],
    }), "season")
    con.close()

    fake_settings = SimpleNamespace(data=SimpleNamespace(warehouse_path=warehouse))
    monkeypatch.setattr("bblmlp.config.load_settings", lambda *a, **k: fake_settings)

    result = runner.invoke(app, ["build", "features", "--season", "2024"])
    assert result.exit_code == 0

    con = connect(warehouse)
    assert con.execute("SELECT COUNT(*) FROM bullpen_features").fetchone()[0] == 2
    con.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_cli.py::test_build_features_writes_bullpen_rows -v`
Expected: FAIL — `bullpen_features` has 0 rows (CLI doesn't write it yet)

- [ ] **Step 3: Wire it into `build_features_cmd`**

In `src/bblmlp/cli.py`, change:

```python
@build_app.command("features")
def build_features_cmd(season: int = typer.Option(..., "--season")) -> None:
    """Compute as-of rolling-window features (team + pitcher grain) for a season.

    Loads `season <= <year>` (not `season = <year>`) from `games`, `team_game_stats`, and
    `pitcher_game_stats` so the trailing windows have real prior-season history to draw on --
    a team's/pitcher's 162/75-game window can then genuinely span a season boundary instead of
    being capped at whatever games exist so far in the target season alone. The builder outputs
    are then filtered back down to just the target season before `replace_partition` writes, so
    the command's write contract is unchanged: it only ever replaces the target season's rows in
    `team_features`/`pitcher_features`, never prior seasons'.
    """
    from bblmlp.config import load_settings
    from bblmlp.features.rolling import pitcher_rolling_features, team_rolling_features
    from bblmlp.storage import connect, init_schema, replace_partition

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    games = con.execute(
        "SELECT game_pk, game_date, game_datetime FROM games WHERE season <= ?", [season]
    ).df()
    team_game_stats = con.execute(
        "SELECT * FROM team_game_stats WHERE season <= ?", [season]
    ).df()
    pitcher_game_stats = con.execute(
        "SELECT * FROM pitcher_game_stats WHERE season <= ?", [season]
    ).df()
    team_features = team_rolling_features(con, team_game_stats, games)
    team_features = team_features[team_features["season"] == season].reset_index(drop=True)
    pitcher_features = pitcher_rolling_features(con, pitcher_game_stats, games)
    pitcher_features = pitcher_features[pitcher_features["season"] == season].reset_index(drop=True)
    team_rows = replace_partition(con, "team_features", team_features, "season")
    pitcher_rows = replace_partition(con, "pitcher_features", pitcher_features, "season")
    con.close()
    typer.echo(f"Wrote {team_rows} team-feature rows and {pitcher_rows} pitcher-feature rows for {season}")
```

to:

```python
@build_app.command("features")
def build_features_cmd(season: int = typer.Option(..., "--season")) -> None:
    """Compute as-of rolling-window features (team + pitcher + bullpen grain) for a season.

    Loads `season <= <year>` (not `season = <year>`) from `games`, `team_game_stats`,
    `pitcher_game_stats`, and `bullpen_game_stats` so the trailing windows have real
    prior-season history to draw on -- a team's/pitcher's/bullpen's 162/75/75-game window
    can then genuinely span a season boundary instead of being capped at whatever games
    exist so far in the target season alone. The builder outputs are then filtered back
    down to just the target season before `replace_partition` writes, so the command's
    write contract is unchanged: it only ever replaces the target season's rows in
    `team_features`/`pitcher_features`/`bullpen_features`, never prior seasons'.
    """
    from bblmlp.config import load_settings
    from bblmlp.features.bullpen import bullpen_rolling_features
    from bblmlp.features.rolling import pitcher_rolling_features, team_rolling_features
    from bblmlp.storage import connect, init_schema, replace_partition

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    games = con.execute(
        "SELECT game_pk, game_date, game_datetime FROM games WHERE season <= ?", [season]
    ).df()
    team_game_stats = con.execute(
        "SELECT * FROM team_game_stats WHERE season <= ?", [season]
    ).df()
    pitcher_game_stats = con.execute(
        "SELECT * FROM pitcher_game_stats WHERE season <= ?", [season]
    ).df()
    bullpen_game_stats = con.execute(
        "SELECT * FROM bullpen_game_stats WHERE season <= ?", [season]
    ).df()
    team_features = team_rolling_features(con, team_game_stats, games)
    team_features = team_features[team_features["season"] == season].reset_index(drop=True)
    pitcher_features = pitcher_rolling_features(con, pitcher_game_stats, games)
    pitcher_features = pitcher_features[pitcher_features["season"] == season].reset_index(drop=True)
    bullpen_features = bullpen_rolling_features(con, bullpen_game_stats, games)
    bullpen_features = bullpen_features[bullpen_features["season"] == season].reset_index(drop=True)
    team_rows = replace_partition(con, "team_features", team_features, "season")
    pitcher_rows = replace_partition(con, "pitcher_features", pitcher_features, "season")
    bullpen_rows = replace_partition(con, "bullpen_features", bullpen_features, "season")
    con.close()
    typer.echo(
        f"Wrote {team_rows} team-feature rows, {pitcher_rows} pitcher-feature rows, "
        f"and {bullpen_rows} bullpen-feature rows for {season}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_cli.py::test_build_features_writes_bullpen_rows -v`
Expected: PASS

- [ ] **Step 5: Run the full test file to verify no regressions**

Run: `uv run --no-sync pytest tests/test_cli.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/bblmlp/cli.py tests/test_cli.py
git commit -m "feat: bblmlp build features writes bullpen_features"
```

---

### Task 6: Full-suite verification, docs, and rollout note

**Files:**
- Modify: `CLAUDE.md` (Current status section)
- Modify: `docs/cli-usage.md` (`build rollups` / `build features` sections)
- No test file — this task verifies and documents; no new production code.

- [ ] **Step 1: Run the entire test suite**

Run: `uv run --no-sync pytest -q`
Expected: All tests pass (110 existing + new tests from Tasks 1-5).

- [ ] **Step 2: Update `docs/cli-usage.md`**

In the `### \`build rollups\`` section, change:

```markdown
### `build rollups` — pitcher/team game stats from Statcast

```bash
bb build rollups --season 2024
```
Writes `pitcher_game_stats` / `team_game_stats`, computed from `statcast_pitches` already
in the warehouse (no network call).
```

to:

```markdown
### `build rollups` — pitcher/team/bullpen game stats from Statcast

```bash
bb build rollups --season 2024
```
Writes `pitcher_game_stats` / `team_game_stats` / `bullpen_game_stats`, computed from
`statcast_pitches` already in the warehouse (no network call). `bullpen_game_stats` is an
exact aggregation of `pitcher_game_stats` rows where `is_starter = false`, grouped by
`(game_pk, team)` — never a subtraction of starter totals from team totals.
```

In the `### \`build features\`` section, change:

```markdown
### `build features` — as-of rolling-window team/pitcher features

```bash
bb build features --season 2024
```
Writes `team_features` (30/162-game trailing windows) and `pitcher_features` (10/35/75-game
trailing windows), computed from `team_game_stats`/`pitcher_game_stats` already in the
warehouse (no network call). Every feature for game N is built only from games strictly
before N. Loads `season <= <year>` internally so windows can span a season boundary, but
only ever writes rows for `--season`.
```

to:

```markdown
### `build features` — as-of rolling-window team/pitcher/bullpen features

```bash
bb build features --season 2024
```
Writes `team_features` (30/162-game trailing windows), `pitcher_features` (10/35/75-game
trailing windows), and `bullpen_features` (10/35/75-game trailing windows, partitioned by
team rather than individual pitcher identity), computed from `team_game_stats` /
`pitcher_game_stats` / `bullpen_game_stats` already in the warehouse (no network call).
Every feature for game N is built only from games strictly before N. Loads `season <=
<year>` internally so windows can span a season boundary, but only ever writes rows for
`--season`.
```

- [ ] **Step 3: Update `CLAUDE.md`'s "Current status" section**

Change the "Not yet built" paragraph from:

```markdown
**Not yet built** (next work, per the design doc): the rest of `features/` beyond the rolling-window
builder (bullpen features, cold-start/shrinkage, batter/lineup features — roadmap #5-#7), the
game-winner model (`models/game/` — Elo baseline → LightGBM + isotonic calibration), the bet
crafter (`betting/`), and backtest (`backtest/`). Kalshi ingestion (`ingest/kalshi/`) is built on
a feature branch, not yet merged to `main`.
```

to:

```markdown
**Not yet built** (next work, per the design doc): the rest of `features/` beyond rolling-window
team/pitcher/bullpen (cold-start/shrinkage, batter/lineup features — roadmap #6-#7), the
game-winner model (`models/game/` — Elo baseline → LightGBM + isotonic calibration), the bet
crafter (`betting/`), and backtest (`backtest/`). Kalshi ingestion (`ingest/kalshi/`) is merged to
`main` (`bblmlp ingest kalshi`).
```

- [ ] **Step 4: Run the full suite one more time to confirm docs changes didn't touch code**

Run: `uv run --no-sync pytest -q`
Expected: All tests still pass, same count as Step 1.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/cli-usage.md
git commit -m "docs: reflect bullpen rolling-window features in CLAUDE.md and cli-usage.md"
```

- [ ] **Step 6: Note the rollout step (do not execute as part of this plan)**

Existing backfilled seasons (2021–2025) need two rebuild passes to actually populate the new
`team` column and the new tables with real data — this is a data operation against the live
warehouse, not something the automated tests perform, and should be run manually after this
branch merges:

```bash
for season in 2021 2022 2023 2024 2025; do
  bb build rollups --season $season
  bb build features --season $season
done
```
