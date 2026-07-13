# Kalshi Snapshot Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `src/bblmlp/ingest/kalshi/`, a minimal discovery-and-recording daemon that
pulls Kalshi's public `KXMLBGAME` (single-game moneyline) markets, joins them to our own
`games` table, and persists every pull as both a `kalshi_quotes` DuckDB table row and a
timestamped Parquet snapshot — with no fee math, edge calc, sizing, or auth (that's step 4 of
the roadmap).

**Architecture:** New `ingest/kalshi/` package mirrors the existing `ingest/mlb/` seam: a
network-only `client.py` (httpx), pure normalizer/matcher functions in `snapshot.py`
(fixture-tested, no network), a static validated `team_map.py`, and an `ingest.py` orchestrator
wired into the CLI as `bblmlp ingest kalshi`. A new `append_rows` warehouse helper handles the
append-only (never-replace) write pattern this table needs, unlike every other table in the
warehouse.

**Tech Stack:** `httpx` (new dependency, matches the original design doc's tech-stack
decision), stdlib `zoneinfo` for DST-aware ET conversion (no new dependency), DuckDB's native
`COPY ... TO ... (FORMAT PARQUET)` (no `pyarrow` needed).

## Global Constraints

- Branch: `feat/kalshi-snapshot-ingest`.
- Run tests with `uv run --no-sync pytest -q`, never bare `pytest` (see CLAUDE.md's `.pth`
  gotcha). If `uv run bblmlp` breaks with `ModuleNotFoundError`, fall back to
  `PYTHONPATH=src .venv/bin/python -m bblmlp.cli <args>`.
- No network calls in unit tests — network stays confined to `client.py`, which (matching
  `live.py`/`players.py`/`standings.py` convention in this repo) is not unit-tested directly;
  only its callers are tested via monkeypatched fixtures.
- Every warehouse writer that touches SQL identifiers must go through `storage.warehouse._q()`
  for quoting (existing convention — reserved words / special chars in column names).
- `kalshi_quotes` is **append-only** — never use `replace_partition`/`replace_all`/`upsert_games`
  for it. This is a deliberate, documented exception to the repo's idempotent-upsert convention.
- Full design context and empirically-validated facts (team codes, ticker HHMM semantics,
  `G1`/`G2` doubleheader suffix, DuckDB parquet/JSON support) live in
  `docs/superpowers/specs/2026-07-12-kalshi-snapshot-ingest-design.md` — read it if a task's
  rationale is unclear.

---

### Task 1: `team_map.py` — validated Kalshi team code map

**Files:**
- Create: `src/bblmlp/ingest/kalshi/__init__.py` (empty, matches `ingest/mlb/__init__.py`)
- Create: `src/bblmlp/ingest/kalshi/team_map.py`
- Test: `tests/test_kalshi_team_map.py`

**Interfaces:**
- Consumes: `bblmlp.ingest.mlb.team_crosswalk.FANGRAPHS_ABBR_BY_TEAM_ID` (dict, keys are the 30
  canonical `team_id`s — used only as the validation source, not for values).
- Produces: `KALSHI_TEAM_CODES: dict[str, int]` — Kalshi's 2-3 letter team code → StatsAPI
  `team_id`. Consumed by Task 4 (`normalize_snapshot`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kalshi_team_map.py
from bblmlp.ingest.kalshi.team_map import KALSHI_TEAM_CODES
from bblmlp.ingest.mlb.team_crosswalk import FANGRAPHS_ABBR_BY_TEAM_ID


def test_every_kalshi_code_maps_to_a_known_team_id():
    # Validated against the real, stable universe of 30 franchise ids (team_crosswalk's
    # own source of truth) so a future relocation/expansion would fail loudly here
    # instead of silently mis-joining Kalshi prices to the wrong game.
    assert set(KALSHI_TEAM_CODES.values()) == set(FANGRAPHS_ABBR_BY_TEAM_ID.keys())


def test_kalshi_codes_are_unique():
    assert len(KALSHI_TEAM_CODES) == 30
    assert len(set(KALSHI_TEAM_CODES.values())) == 30


def test_known_codes_spot_check():
    # Spot-check codes that don't obviously match MLB's own abbreviations
    # (confirmed live against Kalshi's API during design, 2026-07-12).
    assert KALSHI_TEAM_CODES["ATH"] == 133  # Athletics ("A's")
    assert KALSHI_TEAM_CODES["AZ"] == 109  # Diamondbacks (not "ARI")
    assert KALSHI_TEAM_CODES["WSH"] == 120  # Nationals (not "WSN")
    assert KALSHI_TEAM_CODES["KC"] == 118  # Royals (2-letter, not "KCR")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_kalshi_team_map.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bblmlp.ingest.kalshi'`

- [ ] **Step 3: Write the implementation**

```python
# src/bblmlp/ingest/kalshi/__init__.py
```//(empty file)

```python
# src/bblmlp/ingest/kalshi/team_map.py
"""Kalshi's own 2-3 letter team codes -> StatsAPI team_id.

Kalshi team codes don't match any other source's abbreviations (e.g. `ATH` not `OAK`,
`AZ` not `ARI`, `WSH` not `WSN`, `KC`/`SD`/`SF`/`TB` are 2 letters). Neither derivable
nor documented anywhere but Kalshi's own API, so this is a hand-maintained static map --
same pattern as `ingest/mlb/team_crosswalk.py`'s `FANGRAPHS_ABBR_BY_TEAM_ID`, except
`team_id` is relocation-proof (doesn't shift the way an abbreviation does), so no
season-scoped override list is needed here.

Enumerated by pulling every KXMLBGAME market live (`GET /markets?series_ticker=KXMLBGAME
&limit=1000`) on 2026-07-12 -- see
docs/superpowers/specs/2026-07-12-kalshi-snapshot-ingest-design.md #2.1 for the full
derivation (each code's `yes_sub_title` cross-referenced against `team_crosswalk`'s
2025 team names).
"""
from __future__ import annotations

KALSHI_TEAM_CODES: dict[str, int] = {
    "AZ": 109, "ATH": 133, "ATL": 144, "BAL": 110, "BOS": 111,
    "CHC": 112, "CIN": 113, "CLE": 114, "COL": 115, "CWS": 145,
    "DET": 116, "HOU": 117, "KC": 118, "LAA": 108, "LAD": 119,
    "MIA": 146, "MIL": 158, "MIN": 142, "NYM": 121, "NYY": 147,
    "PHI": 143, "PIT": 134, "SD": 135, "SEA": 136, "SF": 137,
    "STL": 138, "TB": 139, "TEX": 140, "TOR": 141, "WSH": 120,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_kalshi_team_map.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/kalshi/__init__.py src/bblmlp/ingest/kalshi/team_map.py tests/test_kalshi_team_map.py
git commit -m "feat: Kalshi team code map, validated against team_crosswalk's 30 team_ids"
```

---

### Task 2: `snapshot.py::parse_market_ticker` — ticker parsing

**Files:**
- Create: `src/bblmlp/ingest/kalshi/snapshot.py`
- Test: `tests/test_kalshi_snapshot.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure string parsing).
- Produces: `parse_market_ticker(market: dict) -> dict` with keys `game_date` (`datetime.date`),
  `hhmm_et` (`str`, e.g. `"1610"`), `game_number` (`int | None`, 1 or 2), `kalshi_team_code`
  (`str`, this market's own side), `other_team_code` (`str`), `is_home` (`bool`). Consumed by
  Task 4.

Note on design: rather than splitting the event slug's `{AWAY}{HOME}` blob by guessing code
lengths against `KALSHI_TEAM_CODES` (as the design doc's high-level sketch suggested), this
parses the **market**-level ticker (which already contains the market's own team code as its
last segment, e.g. `...TORSD-TOR`) and finds that code as a prefix or suffix of the blob. This
is unambiguous with zero guessing, and it naturally handles codes not in `KALSHI_TEAM_CODES`
(e.g. the All-Star game's `AL`/`NL`) without raising — team_id resolution (and thus whether the
row is joinable) is a separate, later concern in Task 4, not a parsing concern here.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kalshi_snapshot.py
import datetime as dt

from bblmlp.ingest.kalshi.snapshot import parse_market_ticker


def test_parse_market_ticker_away_side():
    market = {
        "ticker": "KXMLBGAME-26JUL121610TORSD-TOR",
        "event_ticker": "KXMLBGAME-26JUL121610TORSD",
    }
    parsed = parse_market_ticker(market)
    assert parsed["game_date"] == dt.date(2026, 7, 12)
    assert parsed["hhmm_et"] == "1610"
    assert parsed["game_number"] is None
    assert parsed["kalshi_team_code"] == "TOR"
    assert parsed["other_team_code"] == "SD"
    assert parsed["is_home"] is False


def test_parse_market_ticker_home_side():
    market = {
        "ticker": "KXMLBGAME-26JUL121610TORSD-SD",
        "event_ticker": "KXMLBGAME-26JUL121610TORSD",
    }
    parsed = parse_market_ticker(market)
    assert parsed["kalshi_team_code"] == "SD"
    assert parsed["other_team_code"] == "TOR"
    assert parsed["is_home"] is True


def test_parse_market_ticker_doubleheader_suffix():
    market = {
        "ticker": "KXMLBGAME-26JUL071415MILSTLG1-MIL",
        "event_ticker": "KXMLBGAME-26JUL071415MILSTLG1",
    }
    parsed = parse_market_ticker(market)
    assert parsed["game_number"] == 1
    assert parsed["kalshi_team_code"] == "MIL"
    assert parsed["other_team_code"] == "STL"
    assert parsed["is_home"] is False


def test_parse_market_ticker_all_star_codes_not_in_team_map():
    # AL/NL aren't real franchises (not in KALSHI_TEAM_CODES) but the ticker
    # still parses structurally -- team_id resolution happens later, in normalize_snapshot.
    market = {
        "ticker": "KXMLBGAME-26JUL142000ALNL-NL",
        "event_ticker": "KXMLBGAME-26JUL142000ALNL",
    }
    parsed = parse_market_ticker(market)
    assert parsed["kalshi_team_code"] == "NL"
    assert parsed["other_team_code"] == "AL"
    assert parsed["is_home"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_kalshi_snapshot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bblmlp.ingest.kalshi.snapshot'`

- [ ] **Step 3: Write the implementation**

```python
# src/bblmlp/ingest/kalshi/snapshot.py
"""Pure normalizer/matcher for Kalshi KXMLBGAME markets. No network calls -- everything
here takes already-fetched API payloads (dicts) and our own `games` DataFrame, and is
unit-tested with fixtures.
"""
from __future__ import annotations

import datetime as dt

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_market_ticker(market: dict) -> dict:
    """Parse one KXMLBGAME market's ticker fields.

    Ticker grammar: `KXMLBGAME-{YY}{MMM}{DD}{HHMM}{AWAY}{HOME}[G{N}]-{TEAM}`. `HHMM` is
    the game's originally-scheduled first-pitch time in America/New_York wall-clock,
    frozen at market-creation time (confirmed empirically against MLB StatsAPI --
    NOT UTC, despite the earlier discovery doc's claim; see the design doc's #2).

    The market's own team code (`ticker`'s trailing segment) is matched against the
    event slug's `{AWAY}{HOME}` blob as a prefix or suffix -- unambiguous, no guessing,
    and works even for team codes outside `KALSHI_TEAM_CODES` (e.g. All-Star `AL`/`NL`).
    """
    ticker = market["ticker"]
    event_ticker = market["event_ticker"]
    team_code = ticker.rsplit("-", 1)[-1]
    slug = event_ticker.split("-", 1)[1]  # e.g. "26JUL121610TORSD"

    yy, mmm, dd, hhmm = slug[0:2], slug[2:5], slug[5:7], slug[7:11]
    teams_blob = slug[11:]  # e.g. "TORSD" or "MILSTLG1"

    game_number = None
    if teams_blob[-2:] in ("G1", "G2"):
        game_number = int(teams_blob[-1])
        teams_blob = teams_blob[:-2]

    if teams_blob.startswith(team_code):
        other_team_code = teams_blob[len(team_code):]
        is_home = False
    elif teams_blob.endswith(team_code):
        other_team_code = teams_blob[:-len(team_code)]
        is_home = True
    else:
        raise ValueError(
            f"team code {team_code!r} not found in ticker slug {teams_blob!r} "
            f"(ticker={ticker!r})"
        )

    return {
        "game_date": dt.date(2000 + int(yy), _MONTHS[mmm], int(dd)),
        "hhmm_et": hhmm,
        "game_number": game_number,
        "kalshi_team_code": team_code,
        "other_team_code": other_team_code,
        "is_home": is_home,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_kalshi_snapshot.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/kalshi/snapshot.py tests/test_kalshi_snapshot.py
git commit -m "feat: parse Kalshi KXMLBGAME market tickers (ET wall-clock HHMM, G1/G2 suffix)"
```

---

### Task 3: `snapshot.py::match_game_pk` — doubleheader-safe game join

**Files:**
- Modify: `src/bblmlp/ingest/kalshi/snapshot.py`
- Test: `tests/test_kalshi_snapshot.py`

**Interfaces:**
- Consumes: a `games_df` shaped like `SELECT game_pk, game_date, game_datetime, home_team_id,
  away_team_id FROM games` (real column names from `storage/warehouse.py`'s `GAMES_DDL`).
- Produces: `match_game_pk(games_df, game_date, home_team_id, away_team_id, *,
  game_number=None, hhmm_et=None) -> int | None`. Consumed by Task 4.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kalshi_snapshot.py (append)
import pandas as pd

from bblmlp.ingest.kalshi.snapshot import match_game_pk


def _games_df(rows):
    return pd.DataFrame(rows, columns=["game_pk", "game_date", "game_datetime", "home_team_id", "away_team_id"])


def test_match_game_pk_single_candidate():
    games = _games_df([
        [824816, "2026-07-09", "2026-07-09 17:35:00", 110, 112],
    ])
    assert match_game_pk(games, dt.date(2026, 7, 9), 110, 112) == 824816


def test_match_game_pk_no_candidates_returns_none():
    games = _games_df([[824816, "2026-07-09", "2026-07-09 17:35:00", 110, 112]])
    assert match_game_pk(games, dt.date(2026, 7, 10), 110, 112) is None


def test_match_game_pk_doubleheader_disambiguated_by_game_number():
    # Real doubleheader from our own warehouse: Twins (home, 142) vs Guardians
    # (away, 114) on 2025-09-20 -- two actual games, confirmed via a direct query
    # during the design pass (see design doc's #6 testing section).
    games = _games_df([
        [777839, "2025-09-20", "2025-09-20 18:10:00", 142, 114],
        [776243, "2025-09-20", "2025-09-20 23:10:00", 142, 114],
    ])
    assert match_game_pk(games, dt.date(2025, 9, 20), 142, 114, game_number=1) == 777839
    assert match_game_pk(games, dt.date(2025, 9, 20), 142, 114, game_number=2) == 776243


def test_match_game_pk_doubleheader_disambiguated_by_closest_et_time():
    games = _games_df([
        [777839, "2025-09-20", "2025-09-20 18:10:00", 142, 114],  # 14:10 ET
        [776243, "2025-09-20", "2025-09-20 23:10:00", 142, 114],  # 19:10 ET
    ])
    assert match_game_pk(games, dt.date(2025, 9, 20), 142, 114, hhmm_et="1410") == 777839
    assert match_game_pk(games, dt.date(2025, 9, 20), 142, 114, hhmm_et="1910") == 776243


def test_match_game_pk_ambiguous_doubleheader_with_no_disambiguator_returns_none():
    games = _games_df([
        [777839, "2025-09-20", "2025-09-20 18:10:00", 142, 114],
        [776243, "2025-09-20", "2025-09-20 23:10:00", 142, 114],
    ])
    assert match_game_pk(games, dt.date(2025, 9, 20), 142, 114) is None
```

Add `import datetime as dt` to the top of the test file if not already present from Task 2.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_kalshi_snapshot.py -v`
Expected: FAIL with `ImportError: cannot import name 'match_game_pk'`

- [ ] **Step 3: Write the implementation**

```python
# src/bblmlp/ingest/kalshi/snapshot.py (append)
from zoneinfo import ZoneInfo

import pandas as pd

_ET = ZoneInfo("America/New_York")


def match_game_pk(
    games_df: "pd.DataFrame",
    game_date: dt.date,
    home_team_id: int,
    away_team_id: int,
    *,
    game_number: int | None = None,
    hhmm_et: str | None = None,
) -> int | None:
    """Join a Kalshi market to our `games` table by date + team ids.

    Handles doubleheaders (>1 candidate row): prefers the explicit `game_number`
    (from a `G1`/`G2` ticker suffix) when given, else picks the candidate whose
    `game_datetime` converts to America/New_York wall-clock closest to `hhmm_et`.
    Returns None (never raises) when there's no candidate, or when there's more
    than one and no disambiguator was given -- callers must persist the price
    row anyway with game_pk=NULL rather than drop it (see design doc's core
    "never drop a row" principle).
    """
    gd = pd.to_datetime(games_df["game_date"]).dt.date
    mask = (
        (gd == game_date)
        & (games_df["home_team_id"] == home_team_id)
        & (games_df["away_team_id"] == away_team_id)
    )
    candidates = games_df[mask]
    if len(candidates) == 0:
        return None
    if len(candidates) == 1:
        return int(candidates.iloc[0]["game_pk"])

    candidates = candidates.sort_values("game_datetime")

    if game_number is not None:
        idx = game_number - 1
        if 0 <= idx < len(candidates):
            return int(candidates.iloc[idx]["game_pk"])
        return None

    if hhmm_et is not None:
        target = int(hhmm_et)

        def _et_hhmm(value) -> int:
            local = pd.Timestamp(value).tz_localize("UTC").tz_convert(_ET)
            return local.hour * 100 + local.minute

        diffs = candidates["game_datetime"].map(lambda v: abs(_et_hhmm(v) - target))
        return int(candidates.loc[diffs.idxmin(), "game_pk"])

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_kalshi_snapshot.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/kalshi/snapshot.py tests/test_kalshi_snapshot.py
git commit -m "feat: doubleheader-safe game_pk matching (G1/G2 suffix + closest-ET-time fallback)"
```

---

### Task 4: `snapshot.py::normalize_snapshot` — full row assembly

**Files:**
- Modify: `src/bblmlp/ingest/kalshi/snapshot.py`
- Test: `tests/test_kalshi_snapshot.py`

**Interfaces:**
- Consumes: `KALSHI_TEAM_CODES` (Task 1), `parse_market_ticker`/`match_game_pk` (Tasks 2-3).
- Produces: `normalize_snapshot(markets: list[dict], orderbooks: dict[str, dict], games_df:
  pd.DataFrame, pulled_at: str) -> pd.DataFrame` with columns exactly matching the
  `kalshi_quotes` DDL from Task 5: `pulled_at, event_ticker, market_ticker, game_pk,
  kalshi_team_code, is_home, team_id, yes_bid, yes_ask, no_bid, no_ask, spread, volume_fp,
  open_interest_fp, status, yes_book_json, no_book_json`. Consumed by Task 7.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kalshi_snapshot.py (append)
import json

from bblmlp.ingest.kalshi.snapshot import normalize_snapshot


def _market(ticker, event_ticker, **overrides):
    base = {
        "ticker": ticker,
        "event_ticker": event_ticker,
        "status": "active",
        "yes_bid_dollars": "0.5400",
        "yes_ask_dollars": "0.5500",
        "no_bid_dollars": "0.4500",
        "no_ask_dollars": "0.4600",
        "volume_fp": "15059.00",
        "open_interest_fp": "2851507.04",
    }
    base.update(overrides)
    return base


def _orderbook():
    return {"orderbook_fp": {
        "yes_dollars": [["0.5300", "2270.43"], ["0.5400", "1427.94"]],
        "no_dollars": [["0.4500", "6404.00"], ["0.4600", "1236.38"]],
    }}


def _games_df_for_torsd():
    return pd.DataFrame([
        # TOR (away, 141) @ SD (home, 135), 2026-07-12, ticker HHMM=1610 ET -> 20:10 UTC
        [999001, "2026-07-12", "2026-07-12 20:10:00", 135, 141],
    ], columns=["game_pk", "game_date", "game_datetime", "home_team_id", "away_team_id"])


def test_normalize_snapshot_produces_matched_row_for_away_and_home_sides():
    markets = [
        _market("KXMLBGAME-26JUL121610TORSD-TOR", "KXMLBGAME-26JUL121610TORSD"),
        _market("KXMLBGAME-26JUL121610TORSD-SD", "KXMLBGAME-26JUL121610TORSD",
                yes_bid_dollars="0.4500", yes_ask_dollars="0.4600"),
    ]
    orderbooks = {
        "KXMLBGAME-26JUL121610TORSD-TOR": _orderbook(),
        "KXMLBGAME-26JUL121610TORSD-SD": _orderbook(),
    }
    df = normalize_snapshot(markets, orderbooks, _games_df_for_torsd(), "2026-07-12T12:00:00+00:00")

    assert len(df) == 2
    tor = df[df["kalshi_team_code"] == "TOR"].iloc[0]
    sd = df[df["kalshi_team_code"] == "SD"].iloc[0]

    assert tor["game_pk"] == 999001 and sd["game_pk"] == 999001
    # Not an `is True/False` identity check: a row pulled via `.iloc[0]` can come
    # back as numpy.bool_, which isn't the same object as Python's True/False.
    assert not tor["is_home"] and sd["is_home"]
    assert tor["team_id"] == 141 and sd["team_id"] == 135
    assert tor["yes_bid"] == 0.54 and tor["yes_ask"] == 0.55
    assert tor["spread"] == pytest.approx(0.01)
    assert json.loads(tor["yes_book_json"]) == [["0.5300", "2270.43"], ["0.5400", "1427.94"]]


def test_normalize_snapshot_unmapped_team_code_keeps_row_with_null_game_pk():
    # All-Star game: AL/NL aren't in KALSHI_TEAM_CODES. Price data must still be
    # persisted (never drop a row) with game_pk/team_id as NULL.
    markets = [_market("KXMLBGAME-26JUL142000ALNL-NL", "KXMLBGAME-26JUL142000ALNL")]
    orderbooks = {"KXMLBGAME-26JUL142000ALNL-NL": _orderbook()}
    df = normalize_snapshot(markets, orderbooks, pd.DataFrame(
        columns=["game_pk", "game_date", "game_datetime", "home_team_id", "away_team_id"]
    ), "2026-07-12T12:00:00+00:00")

    assert len(df) == 1
    row = df.iloc[0]
    assert row["kalshi_team_code"] == "NL"
    assert row["is_home"]  # still derivable from ticker position (not an `is True` identity check)
    assert pd.isna(row["team_id"])
    assert pd.isna(row["game_pk"])
    assert row["yes_bid"] == 0.54  # price data preserved regardless


def test_normalize_snapshot_missing_orderbook_leaves_book_columns_empty():
    markets = [_market("KXMLBGAME-26JUL121610TORSD-TOR", "KXMLBGAME-26JUL121610TORSD")]
    df = normalize_snapshot(markets, {}, _games_df_for_torsd(), "2026-07-12T12:00:00+00:00")
    assert df.iloc[0]["yes_book_json"] == "[]"
    assert df.iloc[0]["no_book_json"] == "[]"
```

Add `import pandas as pd` and `import pytest` to the top of the test file if not already
present.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_kalshi_snapshot.py -v`
Expected: FAIL with `ImportError: cannot import name 'normalize_snapshot'`

- [ ] **Step 3: Write the implementation**

```python
# src/bblmlp/ingest/kalshi/snapshot.py (append)
import json

import pandas as pd

from bblmlp.ingest.kalshi.team_map import KALSHI_TEAM_CODES


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def normalize_snapshot(
    markets: list[dict],
    orderbooks: dict[str, dict],
    games_df: pd.DataFrame,
    pulled_at: str,
) -> pd.DataFrame:
    """Turn raw Kalshi market + orderbook payloads into `kalshi_quotes` rows.

    Never drops a row for a failed join or an unmapped team code (e.g. the
    All-Star game's AL/NL) -- price data is irreplaceable (Kalshi has no
    history API), so it's always persisted with game_pk/team_id as NULL when
    they can't be resolved.
    """
    pulled_at_ts = pd.Timestamp(pulled_at)
    rows = []
    for market in markets:
        parsed = parse_market_ticker(market)
        team_code = parsed["kalshi_team_code"]
        other_code = parsed["other_team_code"]
        team_id = KALSHI_TEAM_CODES.get(team_code)
        other_team_id = KALSHI_TEAM_CODES.get(other_code)

        game_pk = None
        if team_id is not None and other_team_id is not None:
            home_team_id = team_id if parsed["is_home"] else other_team_id
            away_team_id = other_team_id if parsed["is_home"] else team_id
            game_pk = match_game_pk(
                games_df, parsed["game_date"], home_team_id, away_team_id,
                game_number=parsed["game_number"], hhmm_et=parsed["hhmm_et"],
            )

        yes_bid = _to_float(market.get("yes_bid_dollars"))
        yes_ask = _to_float(market.get("yes_ask_dollars"))
        book = orderbooks.get(market["ticker"], {}).get("orderbook_fp", {})

        rows.append({
            "pulled_at": pulled_at_ts,
            "event_ticker": market["event_ticker"],
            "market_ticker": market["ticker"],
            "game_pk": game_pk,
            "kalshi_team_code": team_code,
            "is_home": parsed["is_home"],
            "team_id": team_id,
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_bid": _to_float(market.get("no_bid_dollars")),
            "no_ask": _to_float(market.get("no_ask_dollars")),
            "spread": None if yes_bid is None or yes_ask is None else round(yes_ask - yes_bid, 4),
            "volume_fp": _to_float(market.get("volume_fp")),
            "open_interest_fp": _to_float(market.get("open_interest_fp")),
            "status": market.get("status"),
            "yes_book_json": json.dumps(book.get("yes_dollars", [])),
            "no_book_json": json.dumps(book.get("no_dollars", [])),
        })

    return pd.DataFrame(rows, columns=[
        "pulled_at", "event_ticker", "market_ticker", "game_pk", "kalshi_team_code",
        "is_home", "team_id", "yes_bid", "yes_ask", "no_bid", "no_ask", "spread",
        "volume_fp", "open_interest_fp", "status", "yes_book_json", "no_book_json",
    ])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_kalshi_snapshot.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/kalshi/snapshot.py tests/test_kalshi_snapshot.py
git commit -m "feat: normalize Kalshi markets+orderbooks into kalshi_quotes rows"
```

---

### Task 5: `kalshi_quotes` DDL + `append_rows` warehouse helper

**Files:**
- Modify: `src/bblmlp/storage/warehouse.py`
- Modify: `src/bblmlp/storage/__init__.py`
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Produces: `append_rows(con, table: str, df: pd.DataFrame) -> int` and the `kalshi_quotes`
  table (created by `init_schema`). Consumed by Task 7.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_warehouse.py (append)
from bblmlp.storage import append_rows


def test_init_schema_creates_kalshi_quotes_table(tmp_path):
    con = connect(tmp_path / "w.duckdb")
    init_schema(con)
    assert "kalshi_quotes" in table_names(con)


def test_append_rows_accumulates_rather_than_replaces():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE q (pulled_at VARCHAR, v INTEGER)")
    import pandas as pd
    assert append_rows(con, "q", pd.DataFrame({"pulled_at": ["t1"], "v": [1]})) == 1
    assert append_rows(con, "q", pd.DataFrame({"pulled_at": ["t2"], "v": [2]})) == 1
    assert con.execute("SELECT count(*) FROM q").fetchone()[0] == 2  # both pulls kept


def test_append_rows_empty_dataframe_is_a_noop():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE q (v INTEGER)")
    import pandas as pd
    assert append_rows(con, "q", pd.DataFrame({"v": []})) == 0
    assert con.execute("SELECT count(*) FROM q").fetchone()[0] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_warehouse.py -v`
Expected: FAIL with `ImportError: cannot import name 'append_rows'` and a second failure for
the missing `kalshi_quotes` table.

- [ ] **Step 3: Write the implementation**

In `src/bblmlp/storage/warehouse.py`, add the DDL near the other `*_DDL` constants:

```python
KALSHI_QUOTES_DDL = """
CREATE TABLE IF NOT EXISTS kalshi_quotes (
    pulled_at TIMESTAMP NOT NULL,
    event_ticker VARCHAR NOT NULL,
    market_ticker VARCHAR NOT NULL,
    game_pk BIGINT,
    kalshi_team_code VARCHAR NOT NULL,
    is_home BOOLEAN,
    team_id INTEGER,
    yes_bid DOUBLE,
    yes_ask DOUBLE,
    no_bid DOUBLE,
    no_ask DOUBLE,
    spread DOUBLE,
    volume_fp DOUBLE,
    open_interest_fp DOUBLE,
    status VARCHAR,
    yes_book_json VARCHAR,
    no_book_json VARCHAR
);
"""
```

Add it to `init_schema`:

```python
def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(GAMES_DDL)
    con.execute(STATCAST_DDL)
    con.execute(PLAYER_IDS_DDL)
    con.execute(PITCHER_GAME_DDL)
    con.execute(TEAM_GAME_DDL)
    con.execute(STANDINGS_DDL)
    con.execute(LIVE_LINEUPS_DDL)
    con.execute(TEAM_CROSSWALK_DDL)
    con.execute(KALSHI_QUOTES_DDL)
```

Add the writer, near `replace_all`:

```python
def append_rows(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> int:
    """Insert df's rows into table without deleting anything.

    For append-only tables where every write is new point-in-time data, never a
    correction of a prior write (e.g. `kalshi_quotes` -- unlike every other table
    in this warehouse, re-running a pull must NOT replace prior rows).
    """
    if df is None or len(df) == 0:
        return 0
    cols = ", ".join(_q(c) for c in df.columns)
    con.register("_df_append", df)
    try:
        con.execute(f"INSERT INTO {_q(table)} ({cols}) SELECT {cols} FROM _df_append")
    finally:
        con.unregister("_df_append")
    return len(df)
```

In `src/bblmlp/storage/__init__.py`, add `append_rows` to the import and `__all__`:

```python
from bblmlp.storage.warehouse import (
    append_rows,
    connect,
    ensure_table_from_df,
    init_schema,
    replace_all,
    replace_partition,
    table_names,
    upsert_games,
)

__all__ = [
    "append_rows",
    "connect",
    "ensure_table_from_df",
    "init_schema",
    "replace_all",
    "replace_partition",
    "table_names",
    "upsert_games",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_warehouse.py -v`
Expected: all passed (existing + 3 new)

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/storage/warehouse.py src/bblmlp/storage/__init__.py tests/test_warehouse.py
git commit -m "feat: kalshi_quotes table + append_rows (append-only writer)"
```

---

### Task 6: `client.py` — Kalshi network client + `httpx` dependency

**Files:**
- Create: `src/bblmlp/ingest/kalshi/client.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `fetch_open_markets(series: str = "KXMLBGAME") -> list[dict]`,
  `fetch_orderbook(market_ticker: str, depth: int = 10) -> dict`. Consumed by Task 7.
- No test file for this task — matches this repo's existing convention that live network
  functions (`fetch_chadwick`, `fetch_standings`, `fetch_schedule`, `live.py`'s
  `fetch_today_games`) are not unit-tested directly; only their normalizer/caller functions
  are, via injected fixtures.

- [ ] **Step 1: Add the dependency**

```bash
uv add httpx
```

Verify `pyproject.toml`'s `dependencies` list now includes an `httpx>=...` entry.

- [ ] **Step 2: Write the implementation**

```python
# src/bblmlp/ingest/kalshi/client.py
"""Kalshi trade API client: network calls only. Phase 1 reads are public, no auth
(the RSA-PSS signer for live trading is out of scope for this ingest-only work).
"""
from __future__ import annotations

import httpx

_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


def fetch_open_markets(series: str = "KXMLBGAME") -> list[dict]:
    """Fetch every currently-open market for a series, following pagination."""
    markets: list[dict] = []
    cursor: str | None = None
    with httpx.Client(base_url=_BASE_URL, timeout=30.0) as client:
        while True:
            params = {"series_ticker": series, "status": "open", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            resp = client.get("/markets", params=params)
            resp.raise_for_status()
            data = resp.json()
            markets.extend(data.get("markets", []))
            cursor = data.get("cursor") or None
            if not cursor:
                break
    return markets


def fetch_orderbook(market_ticker: str, depth: int = 10) -> dict:
    """Fetch the order book for a single market."""
    with httpx.Client(base_url=_BASE_URL, timeout=30.0) as client:
        resp = client.get(f"/markets/{market_ticker}/orderbook", params={"depth": depth})
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 3: Sanity-check it against the live API (manual, not a unit test)**

```bash
PYTHONPATH=src .venv/bin/python -c "
from bblmlp.ingest.kalshi.client import fetch_open_markets, fetch_orderbook
markets = fetch_open_markets()
print(f'{len(markets)} open markets')
if markets:
    print(markets[0]['ticker'])
    print(fetch_orderbook(markets[0]['ticker']))
"
```

Expected: prints a market count with no exception (count may be 0 or small if run outside
the season / during an off day — that's fine, this step is checking the HTTP plumbing works,
not that games exist right now).

- [ ] **Step 4: Commit**

```bash
git add src/bblmlp/ingest/kalshi/client.py pyproject.toml uv.lock
git commit -m "feat: Kalshi API client (httpx, public reads only)"
```

---

### Task 7: `ingest.py` — orchestrator (pull -> normalize -> persist)

**Files:**
- Create: `src/bblmlp/ingest/kalshi/ingest.py`
- Test: `tests/test_kalshi_ingest.py`

**Interfaces:**
- Consumes: `fetch_open_markets`/`fetch_orderbook` (Task 6, injected as params for
  testability, same pattern as `ingest/mlb/ingest.py` taking `fetch_schedule` as a param),
  `normalize_snapshot` (Task 4), `append_rows` (Task 5).
- Produces: `pull_and_snapshot(con, snapshot_dir, *, fetch_markets=fetch_open_markets,
  fetch_book=fetch_orderbook, pulled_at=None) -> int`. Consumed by Task 8 (CLI).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kalshi_ingest.py
import datetime as dt

import duckdb

from bblmlp.ingest.kalshi.ingest import pull_and_snapshot
from bblmlp.storage import init_schema, upsert_games


def _fake_markets():
    return [
        {
            "ticker": "KXMLBGAME-26JUL121610TORSD-TOR",
            "event_ticker": "KXMLBGAME-26JUL121610TORSD",
            "status": "active",
            "yes_bid_dollars": "0.4600", "yes_ask_dollars": "0.4700",
            "no_bid_dollars": "0.5300", "no_ask_dollars": "0.5400",
            "volume_fp": "23083.00", "open_interest_fp": "1000.00",
        },
        {
            "ticker": "KXMLBGAME-26JUL121610TORSD-SD",
            "event_ticker": "KXMLBGAME-26JUL121610TORSD",
            "status": "active",
            "yes_bid_dollars": "0.5300", "yes_ask_dollars": "0.5400",
            "no_bid_dollars": "0.4600", "no_ask_dollars": "0.4700",
            "volume_fp": "15059.00", "open_interest_fp": "900.00",
        },
    ]


def _fake_orderbook(_ticker):
    return {"orderbook_fp": {"yes_dollars": [["0.5300", "100.00"]], "no_dollars": [["0.4600", "50.00"]]}}


def _game_row():
    return {
        "game_pk": 999001, "season": 2026, "game_date": "2026-07-12",
        "game_datetime": "2026-07-12T20:10:00Z", "home_team": "San Diego Padres",
        "away_team": "Toronto Blue Jays", "home_team_id": 135, "away_team_id": 141,
        "home_probable_pitcher": None, "away_probable_pitcher": None,
        "venue": "Petco Park", "status": "Scheduled",
        "home_score": None, "away_score": None, "home_win": None,
    }


def test_pull_and_snapshot_writes_rows_and_parquet(tmp_path):
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    init_schema(con)
    upsert_games(con, [_game_row()])

    n = pull_and_snapshot(
        con, tmp_path / "snapshots",
        fetch_markets=lambda series="KXMLBGAME": _fake_markets(),
        fetch_book=_fake_orderbook,
        pulled_at=dt.datetime(2026, 7, 12, 12, 0, 0, tzinfo=dt.timezone.utc),
    )

    assert n == 2
    assert con.execute("SELECT count(*) FROM kalshi_quotes").fetchone()[0] == 2
    matched = con.execute(
        "SELECT count(*) FROM kalshi_quotes WHERE game_pk = 999001"
    ).fetchone()[0]
    assert matched == 2

    parquet_files = list((tmp_path / "snapshots").glob("*.parquet"))
    assert len(parquet_files) == 1
    # Read back via DuckDB itself, not pandas -- pd.read_parquet needs a pyarrow/
    # fastparquet engine, and the design deliberately avoids a pyarrow dependency
    # (DuckDB writes and reads Parquet natively; see design doc's #2.5).
    roundtrip_count = duckdb.sql(
        f"SELECT count(*) FROM read_parquet('{parquet_files[0]}')"
    ).fetchone()[0]
    assert roundtrip_count == 2


def test_pull_and_snapshot_second_call_appends_not_replaces(tmp_path):
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    init_schema(con)
    upsert_games(con, [_game_row()])

    kwargs = dict(
        fetch_markets=lambda series="KXMLBGAME": _fake_markets(),
        fetch_book=_fake_orderbook,
    )
    pull_and_snapshot(con, tmp_path / "snapshots", pulled_at=dt.datetime(2026, 7, 12, 12, 0, 0, tzinfo=dt.timezone.utc), **kwargs)
    pull_and_snapshot(con, tmp_path / "snapshots", pulled_at=dt.datetime(2026, 7, 12, 12, 30, 0, tzinfo=dt.timezone.utc), **kwargs)

    assert con.execute("SELECT count(*) FROM kalshi_quotes").fetchone()[0] == 4
    assert len(list((tmp_path / "snapshots").glob("*.parquet"))) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_kalshi_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bblmlp.ingest.kalshi.ingest'`

- [ ] **Step 3: Write the implementation**

```python
# src/bblmlp/ingest/kalshi/ingest.py
"""Kalshi snapshot orchestrator: pull open markets -> normalize/match -> persist.

Every call is one timestamped pull. Unlike the MLB ingest orchestrator, there's no
--date/--backfill mode -- Kalshi has no historical replay endpoint, only "what's open
right now" (see design doc #5).
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import duckdb

from bblmlp.ingest.kalshi.client import fetch_open_markets, fetch_orderbook
from bblmlp.ingest.kalshi.snapshot import normalize_snapshot
from bblmlp.storage import append_rows


def pull_and_snapshot(
    con: duckdb.DuckDBPyConnection,
    snapshot_dir: str | Path,
    *,
    fetch_markets=fetch_open_markets,
    fetch_book=fetch_orderbook,
    pulled_at: _dt.datetime | None = None,
) -> int:
    pulled_at = pulled_at or _dt.datetime.now(_dt.timezone.utc)

    markets = fetch_markets()
    orderbooks = {m["ticker"]: fetch_book(m["ticker"]) for m in markets}
    games_df = con.execute(
        "SELECT game_pk, game_date, game_datetime, home_team_id, away_team_id FROM games"
    ).df()

    df = normalize_snapshot(markets, orderbooks, games_df, pulled_at.isoformat())
    if len(df) == 0:
        return 0

    n = append_rows(con, "kalshi_quotes", df)

    snap_dir = Path(snapshot_dir)
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_path = snap_dir / f"{pulled_at.strftime('%Y%m%dT%H%M%SZ')}.parquet"
    con.register("_kalshi_snap_df", df)
    try:
        con.execute(f"COPY (SELECT * FROM _kalshi_snap_df) TO '{snap_path}' (FORMAT PARQUET)")
    finally:
        con.unregister("_kalshi_snap_df")

    return n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_kalshi_ingest.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/bblmlp/ingest/kalshi/ingest.py tests/test_kalshi_ingest.py
git commit -m "feat: Kalshi pull-and-snapshot orchestrator (parquet + kalshi_quotes)"
```

---

### Task 8: `bblmlp ingest kalshi` CLI command

**Files:**
- Modify: `src/bblmlp/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `pull_and_snapshot` (Task 7).
- Produces: the `ingest kalshi` Typer subcommand.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py (append)
def test_ingest_kalshi_command_exists():
    result = runner.invoke(app, ["ingest", "kalshi", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_cli.py -v`
Expected: FAIL (non-zero exit code / "No such command 'kalshi'")

- [ ] **Step 3: Write the implementation**

In `src/bblmlp/cli.py`, add after the `ingest_players` command:

```python
@ingest_app.command("kalshi")
def ingest_kalshi() -> None:
    """Pull today's open Kalshi KXMLBGAME markets and snapshot prices."""
    from bblmlp.config import load_settings
    from bblmlp.ingest.kalshi.ingest import pull_and_snapshot
    from bblmlp.storage import connect, init_schema

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    n = pull_and_snapshot(con, settings.data.snapshot_dir)
    con.close()
    typer.echo(f"Wrote {n} Kalshi quote rows")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_cli.py -v`
Expected: all passed

- [ ] **Step 5: Run the full suite**

Run: `uv run --no-sync pytest -q`
Expected: all passed, no regressions (baseline was 57 before this plan)

- [ ] **Step 6: Commit**

```bash
git add src/bblmlp/cli.py tests/test_cli.py
git commit -m "feat: bblmlp ingest kalshi CLI command"
```

---

## After all tasks: manual live verification (not a task, a note for whoever runs this)

The test suite runs entirely against fixtures. Before relying on this for real snapshotting,
someone should run `PYTHONPATH=src .venv/bin/python -m bblmlp.cli ingest mlb --date
<today>` (populate `games`) followed by `bblmlp ingest kalshi` against the live API on an
actual game day, then spot-check a few `kalshi_quotes` rows have non-NULL `game_pk` — the
fixture tests can't catch a live schema drift the way `docs/kalshi/2026-07-09-...` warned
about (`*_dollars` fields going away again, cursor pagination format changing, etc.).
