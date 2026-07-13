# Kalshi Snapshot Ingest — minimal daemon (Service 4, step 1)

> Design doc · 2026-07-12 · Status: **draft, awaiting user review**
> Implements roadmap issue #3 (`docs/roadmap/2026-07-11-research-backlog.md`), the "step 1"
> item that jumps the queue ahead of `features/`/`models/game/` because Kalshi serves no
> price history — every un-snapshotted day is unrecoverable L2 backtest data.

## 1. Goal

Discover today's `KXMLBGAME` (single-game moneyline) markets on Kalshi's public API, capture
their prices and order-book depth, and persist a durable, timestamped record — so a price
history accrues for L2 strategy backtesting once it exists. **Explicitly not in scope:** fee
math, edge calculation, sizing, or any live-trading auth (all deferred to step 4, per the
roadmap). This is data hoarding only.

**Success criteria:**
- Running `bblmlp ingest kalshi` repeatedly (e.g. via cron) accumulates a growing, queryable
  price history with no data loss, even for markets that can't be joined to a `game_pk`.
- Every price row is traceable back to a `games` row wherever a match is possible, including on
  doubleheader days.
- No new assumption is baked in without being checked against live data first (see §2).

## 2. Empirically validated findings (checked against the live API 2026-07-12)

These correct or firm up claims from the earlier discovery doc
(`docs/kalshi/2026-07-09-kalshi-mlb-market-discovery.md`):

1. **Team codes (all 30 + AL/NL) are fully enumerated**, not partially guessed. Pulled live from
   `/markets?series_ticker=KXMLBGAME&limit=1000`: `AZ, ATH, ATL, BAL, BOS, CHC, CIN, CLE, COL,
   CWS, DET, HOU, KC, LAA, LAD, MIA, MIL, MIN, NYM, NYY, PHI, PIT, SD, SEA, SF, STL, TB, TEX, TOR,
   WSH` (plus `AL`/`NL` for the All-Star game, which is skipped — see §4).
2. **Ticker `HHMM` is NOT UTC.** It's the game's **originally-scheduled first-pitch time in
   America/New_York wall-clock**, frozen at market-creation time — confirmed against 928 tickers
   (100% match to each market's own `rules_primary` text) and cross-checked against 578 of them
   against MLB StatsAPI's actual schedule (577/578 exact match; the one mismatch was a
   post-creation game-time change, which is itself informative — see next point). This was
   directly re-confirmed against our own freshly-ingested `games` row for that exact game
   (`game_pk=824816`, BAL/CHC, `game_datetime` 17:35 UTC = 13:35 ET, vs. ticker's frozen 18:35 ET).
3. **`occurrence_datetime` / `expected_expiration_time` are not game-start time at all** — they
   equal `scheduled_start_ET + 3:00:00`, a settlement-window marker. Don't use them for matching.
4. **Kalshi sometimes encodes doubleheaders explicitly**: ticker suffix `G1`/`G2` (e.g.
   `KXMLBGAME-26JUL071415MILSTLG1`), confirmed against StatsAPI's `gameNumber`. Coverage is
   incomplete — in 3 of 4 observed doubleheaders Kalshi only created a market for one game — so
   this can't be the only disambiguation path.
5. **DuckDB writes Parquet natively** (`COPY (SELECT ...) TO 'x.parquet' (FORMAT PARQUET)`) and
   can store/query a JSON string column (`json_extract`) — no `pyarrow` dependency needed.
6. **`games` has zero 2026 rows today** — nothing has run live ingest yet. `bblmlp ingest mlb
   --date 2026-07-09` was tested during this design pass and works (13 games ingested,
   `game_datetime` confirmed UTC/tz-naive as documented). The Kalshi ingest command will assume
   `games` already has the target date's slate; it does not ingest schedule itself, matching the
   existing service-separation ("① ingest MLB" and "② ingest Kalshi" are independent CLI
   commands, not chained).

## 3. Module layout

New `src/bblmlp/ingest/kalshi/`, following the `ingest/mlb/` seam (network client separate from
pure normalizers, same as `statcast.py`/`standings.py`):

- **`client.py`** — network only. `fetch_open_markets(series="KXMLBGAME")` (paginates via
  `cursor`), `fetch_orderbook(market_ticker, depth=10)`. Uses `httpx` (per the original design
  doc's tech-stack decision). No auth — Phase 1 reads are public.
- **`team_map.py`** — `KALSHI_TEAM_CODES: dict[str, int]`, the 30 codes from §2.1 mapped straight
  to `team_id` (stable across relocations/renames, unlike abbreviations — no override mechanism
  needed the way `FANGRAPHS_ABBR_OVERRIDES` needs one).
- **`snapshot.py`** — pure normalizer/matcher, unit-testable with fixtures, no network:
  - `parse_event_ticker(ticker) -> dict` — splits `{YY}{MMM}{DD}{HHMM}{AWAY}{HOME}[G{N}]` using
    the known-code set (codes are 2-3 chars, so splitting `TORSD` requires trying the longer
    prefix first against `KALSHI_TEAM_CODES`).
  - `match_game_pk(games_df, game_date, home_team_id, away_team_id, *, game_number=None,
    ticker_hhmm_et=None) -> int | None` — join order: **(1)** if `>1` candidate and a `G1`/`G2`
    suffix was present, pick by sorted `game_datetime` position; **(2)** else if `>1` candidate,
    convert each candidate's `game_datetime` (UTC, tz-naive) to `America/New_York` via
    `zoneinfo.ZoneInfo` (stdlib, DST-aware, no new dependency) and pick the closest to
    `ticker_hhmm_et`; **(3)** if exactly 1 candidate, return it directly (no time comparison
    needed — this is the common case); **(4)** if 0 candidates or still ambiguous, return `None`.
  - `normalize_snapshot(markets, orderbooks, pulled_at) -> pd.DataFrame` — one row per market.
- **`ingest.py`** — orchestrator: pull → normalize/match → write parquet + `kalshi_quotes`.

**Core principle: never drop a row for a failed join.** If `match_game_pk` returns `None`
(unmapped code, All-Star game, ambiguous doubleheader), the price row is still written with
`game_pk = NULL` and a logged warning. Kalshi prices are irreplaceable — persist first, join
opportunistically. A later backfill script can re-run the join against rows with `game_pk IS
NULL` once more `games` data exists, without re-fetching Kalshi.

## 4. Data model

**`kalshi_quotes`** (new DuckDB table). Unlike every other table in this warehouse, this is
**append-only** — `replace_partition`/`upsert` don't apply, because every pull is new
point-in-time data, never a correction of a prior pull. This is a deliberate, documented
exception to CLAUDE.md's idempotency-on-key convention; a new `append_rows` warehouse helper is
added (plain `INSERT`, no delete-then-insert).

| column | type | notes |
|---|---|---|
| `pulled_at` | TIMESTAMP | UTC time of this pull |
| `event_ticker` | VARCHAR | |
| `market_ticker` | VARCHAR | |
| `game_pk` | BIGINT | nullable — NULL if join failed |
| `kalshi_team_code` | VARCHAR | e.g. `TOR` |
| `is_home` | BOOLEAN | derived from ticker position (home segment of the slug) — always
  determinable, independent of whether the code maps to a `team_id` |
| `team_id` | INTEGER | nullable if code unmapped (e.g. `AL`/`NL`) — `game_pk` is then always
  NULL too, since matching requires both team ids |
| `yes_bid`, `yes_ask`, `no_bid`, `no_ask` | DOUBLE | parsed from `*_dollars` |
| `spread` | DOUBLE | `yes_ask - yes_bid` |
| `volume_fp`, `open_interest_fp` | DOUBLE | as reported, fixed-point |
| `status` | VARCHAR | `active` / `finalized` / etc. |
| `yes_book_json`, `no_book_json` | VARCHAR | depth-10 orderbook ladders, raw JSON — lets step
  #9 (order-book price selection) revisit depth-weighted pricing later without a re-scrape |

Every pull also writes the same rows as a timestamped Parquet file under
`data/kalshi_snapshots/` (already configured in `settings.yaml` as `snapshot_dir`) — this is the
durable, replayable source of truth; the DuckDB table is for convenient querying/joins.

## 5. CLI

`bblmlp ingest kalshi` — **no `--date` flag.** Unlike the MLB commands, Kalshi has no historical
replay endpoint; `status=open` always returns whatever's currently tradeable (which naturally
spans a few days ahead, since markets open ~3 days pre-game per observed `open_time`). Each
invocation is exactly one timestamped pull. Designed to be run repeatedly via external cron/
launchd (setup itself is out of scope for this work, per prior discussion).

## 6. Testing

Fixture-based, no network in tests (matches `tests/test_standings.py` convention):
- `parse_event_ticker`: standard tickers, a `G1`/`G2` ticker, and a 2-char-code vs. 3-char-code
  split case (e.g. `SD` vs `TOR`).
- `match_game_pk`: single-candidate case; a **real doubleheader fixture** built from data already
  in our warehouse (e.g. 2025-09-20, two games between the same teams at `18:10` and `23:10` UTC
  — confirmed present via a direct query during this design pass) exercising both the `G1`/`G2`
  path and the closest-ET-time fallback path; zero-candidate (unmatched) case returns `None`
  without raising.
- `normalize_snapshot`: market+orderbook fixture → row shape, including a market with no
  orderbook data (finalized/settled markets return closed books).
- `team_map`: every `KALSHI_TEAM_CODES` value is a `team_id` present in `team_crosswalk`.
- `append_rows` (warehouse helper): two calls accumulate rows rather than replacing them.

## 7. Explicitly out of scope (deferred to step 4, roadmap issue #9/#10)

- Fee math, edge calculation, Kelly sizing, risk gauntlet.
- The RSA-PSS auth signer (dormant per the original design doc; not needed for public reads).
- Order-book price *selection* logic (best bid/ask/mid/depth-weighted) — this step only
  *captures* enough depth (`yes_book_json`/`no_book_json`) to make that decision possible later.
- Spread (`KXMLBSPREAD`) and total (`KXMLBTOTAL`) markets — moneyline (`KXMLBGAME`) only, per D1
  in the roadmap.
- Actual cron/launchd schedule installation.

## 8. Open risk carried forward

Kalshi doesn't always create a market for both games of a doubleheader (3/4 observed cases were
single-game only), and the `G1`/`G2` suffix itself isn't present on every doubleheader ticker
before that partial-coverage fact is accounted for. The ET-wall-clock fallback in `match_game_pk`
is the safety net for the suffix-absent cases; a rescheduled game (ticker time frozen at
creation, per finding #2) could theoretically still misjoin a doubleheader if both games' actual
times end up close together after rescheduling. Given this is a low-frequency edge case, the
mitigation is the `game_pk IS NULL` + logged-warning fallback (§3), not a more complex algorithm.
