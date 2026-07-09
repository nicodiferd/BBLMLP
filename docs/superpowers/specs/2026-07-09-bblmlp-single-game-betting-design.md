# BBLMLP — Baseball ML Prediction for Kalshi (Phase 1: Single-Game Winners)

> Design doc · 2026-07-09 · Status: **approved, ready for planning**

## 1. Goal

Build a **local, Python** system that predicts MLB **single-game winners**, compares
those predictions against **Kalshi** market prices, and produces a daily **recommended
bet slip** — starting in **paper/backtest mode**, with no automated order execution.

**Success criteria (Phase 1):**
- One command runs the daily pipeline end-to-end on this machine.
- The game-winner model is **well-calibrated** (Brier score + reliability curve), not just accurate.
- The bet crafter outputs a slip with, per pick: model probability, Kalshi price, fee-adjusted edge, Kelly-sized stake, and expected value.
- Kalshi markets for the day are ingested and **snapshotted to disk** so a price history accrues for later strategy backtesting.

## 2. Scope

**In scope (Phase 1):**
- MLB data ingestion: full historical backfill + daily live pull.
- Feature engineering: team + starting-pitcher features, point-in-time (no leakage).
- Game-winner model: Elo baseline → LightGBM with isotonic calibration.
- Kalshi ingestion: public REST snapshots of the day's baseball game markets.
- Bet crafter: fee-adjusted edge → fractional Kelly → risk gauntlet → slip.
- Backtest: model-quality metrics now; strategy replay as snapshots accumulate.

**Out of scope (deferred):**
- **Player props** → see `2026-07-09-player-props-feature-spec.md` (Phase 2).
- Live/automated order execution (auth signer is ported but dormant).
- WebSocket real-time feeds.
- Any hosting/deployment — everything runs locally, forever.

**Non-goals:** a UI beyond a CLI/CSV/markdown slip (a local Streamlit dashboard is an optional later add-on).

## 3. Architecture

Daily pipeline, five independently runnable/testable units:

```
① ingest MLB      ② ingest Kalshi        ③ project           ④ craft
(hist + live) ──▶  (today's game    ──▶  (game-winner   ──▶   (fee-adj edge →
 → DuckDB           markets + prices,      model → win           Kelly size →
                    snapshot to disk)      probabilities)        risk gauntlet → slip)

                          ⑤ backtest  (offline: L1 model calibration; L2 strategy replay)
```

Each unit reads/writes the DuckDB warehouse and is invoked through one `bblmlp` CLI.

## 4. Repo layout

```
BBLMLP/
├── pyproject.toml            # deps managed with uv
├── .env                      # Kalshi keys (gitignored) — only needed when going live
├── config/settings.yaml      # data paths, seasons, model + staking params
├── data/                     # gitignored
│   ├── warehouse.duckdb       # single local analytical store
│   ├── kalshi_snapshots/      # timestamped raw market snapshots (parquet)
│   └── models/                # serialized trained models
├── src/bblmlp/
│   ├── ingest/mlb/           # service 1
│   ├── ingest/kalshi/        # service 4 (client, auth signer [dormant], snapshotter)
│   ├── features/             # service 2 (as-of feature builders)
│   ├── models/game/          # service 3 (elo, lgbm, calibration, projection)
│   ├── betting/              # service 5 (fees.py, edge.py, sizing.py, risk.py, crafter.py)
│   ├── backtest/             # service 5 (model metrics + strategy replay)
│   ├── storage/              # DuckDB access layer + schema
│   └── cli.py                # Typer: `bblmlp ingest|project|craft|backtest`
├── docs/superpowers/specs/   # this doc + props feature spec
├── notebooks/                # exploration
└── tests/
```

## 5. Tech stack (decided)

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Ecosystem for baseball data + ML |
| Deps | **uv** | Fast, reproducible, single `pyproject.toml` |
| Storage | **DuckDB** (single file) + Parquet snapshots | Fast columnar SQL over pitch-level Statcast; no server |
| CLI | **Typer** | One `bblmlp` command, subcommands per service |
| Scheduling | local **cron/launchd** (manual to start) | No orchestrator needed on one machine |
| Data libs | pandas/polars, `pybaseball`, `MLB-StatsAPI` | Historical + live MLB data |
| Modeling | scikit-learn, **LightGBM**, isotonic calibration | Accuracy + calibration |
| Kalshi | `httpx` + `cryptography` (auth signer) | Port of the Rust client |

## 6. Service specs

### Service 1 — MLB data (`ingest/mlb/`)
- **Historical backfill:** `pybaseball` for Statcast (pitch-level), standings, schedules, FanGraphs team/pitcher stats. Throttle + cache raw pulls; land normalized tables in DuckDB.
- **Daily live:** `MLB-StatsAPI` for schedule, probable pitchers, lineups, and final scores.
- **Landing tables (DuckDB):** `games`, `team_game_stats`, `pitcher_game_stats`, `statcast_pitches` (partitioned by season), `schedule_today`.
- Idempotent upserts keyed on `game_pk`. Backfill scope configurable (default: last ~5 seasons).

### Service 2 — Feature engineering (`features/`)
- Build **point-in-time "as-of" tables**: every feature uses only information known **before first pitch** (guards against leakage — the single biggest backtest trap).
- Phase-1 feature families:
  - **Team form:** Elo rating, rolling run differential, recent W-L, wRC+, bullpen ERA/FIP.
  - **Starting pitcher:** season/rolling xwOBA, K%, BB%, handedness.
  - **Context:** home/away, park factor, rest days, travel, probable-pitcher matchup handedness.
- Output: one row per (game, home/away) with a stable feature schema consumed by the model.

### Service 3 — Game-winner model (`models/game/`)
- **Baseline:** Elo / Bradley-Terry — robust, interpretable, near-calibrated. Always kept as a benchmark.
- **Primary:** **LightGBM** classifier on the feature table, wrapped in **isotonic calibration** (fit on a held-out slice).
- **Selection metric:** **Brier score + reliability curve** (calibration), with log-loss secondary. Accuracy is reported but not the objective.
- **Validation:** time-series/walk-forward split by date (never random shuffle — prevents future leakage).
- **Output:** calibrated `P(home win)` per game, written to a `projections` table with model version + timestamp.

### Service 4 — Kalshi ingestion (`ingest/kalshi/`)
Ported from `polymarket-arbitrage-rust` (`src/traders/kalshi.rs`, `src/watchers/kalshi.rs`, `docs/kalshi-api-reference.md`).

- **Hosts:** prod `https://api.elections.kalshi.com/trade-api/v2`, demo `https://demo-api.kalshi.co/trade-api/v2`.
- **Reads are public** — `GET /markets?series_ticker=…&status=open&limit=200` and `GET /markets/{ticker}/orderbook` need **no auth**. Phase 1 uses only these.
- **Market discovery task:** the old repo only watched championship futures (`KXMLB`). We must discover the **single-game series ticker(s)** (candidates like `KXMLBGAME`) via `/series` + `/events` and confirm the ticker format. This is the first Kalshi work item.
- **Mapping:** join each Kalshi game market to our internal `game_pk` by teams + date.
- **Snapshotting:** every pull writes a **timestamped parquet snapshot** to `data/kalshi_snapshots/` AND a row to a DuckDB `kalshi_quotes` table. This is how we build the price history that L2 backtesting needs (Kalshi serves no deep history).
- **Auth signer (dormant, ported for later):** RSA-PSS SHA-256, message = `{ms_timestamp}{METHOD}{path_without_query}`, headers `KALSHI-ACCESS-KEY / -TIMESTAMP / -SIGNATURE`; key must be PKCS#8. Implemented + unit-tested but unused in paper mode.

### Service 5 — Bet crafter + backtest (`betting/`, `backtest/`)
Betting math ported from the old repo's researched + tested logic (`docs/kalshi-fee-schedule.md`, `docs/kelly-criterion.md`, `docs/risk-management.md`, `src/engine/`).

- **Fees (`fees.py`):** taker `ceil(0.07·C·P·(1−P))`, maker `ceil(0.0175·C·P·(1−P))`, prices in dollars, round up to cent. **Sports markets DO charge maker fees** — account for both.
- **Edge (`edge.py`):** fee-adjusted edge `= (p − P) − fee_per_contract/(1 − P)`, where `p` = model prob, `P` = Kalshi price.
- **Sizing (`sizing.py`):** simplified prediction-market Kelly `f* = (p − P)/(1 − P)`, then **quarter Kelly** (`kelly_fraction = 0.25`), capped at `max_risk_per_trade = 0.05`.
- **Risk gauntlet (`risk.py`):** min-confidence (0.55) → positive Kelly → drawdown halt (20%) → daily-loss limit → 5%/trade cap. All defaults ported; configurable in `settings.yaml`.
- **Crafter (`crafter.py`):** for each mapped market, run edge → sizing → gauntlet; emit a daily **slip** (markdown + CSV) with per-pick prob, price, edge, stake, EV, and the gauntlet decision.
- **Backtest:**
  - **L1 (today):** model calibration/quality on historical games — Brier, log-loss, reliability curve, walk-forward.
  - **L2 (accrues):** strategy replay over stored `kalshi_quotes` — P&L, ROI, CLV, drawdown. **Gated on snapshot history**, so it strengthens over the season.
  - **L3 (later):** Monte-Carlo bankroll/drawdown simulation.

## 7. Configuration (`config/settings.yaml`)

- `data`: warehouse path, snapshot dir, backfill seasons.
- `kalshi`: `use_demo`, host override, baseball series tickers, poll cadence.
- `model`: feature window sizes, calibration holdout, model version tag.
- `staking`: `kelly_fraction=0.25`, `max_risk_per_trade=0.05`, `max_drawdown=0.20`, `daily_loss_limit`, `min_confidence=0.55`.
- Secrets (`KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`) live in `.env`, only needed once we go live.

## 8. Testing strategy

- Unit tests for: auth signing (known message → signature format), fee formula (against the doc's fee curve), Kelly sizing (edge cases: no edge → 0), edge calc, as-of feature leakage guards.
- Data-contract tests on DuckDB table schemas.
- A tiny fixture dataset for a deterministic end-to-end pipeline smoke test.
- Model validation is walk-forward only; a test asserts no random-shuffle split sneaks in.

## 9. Risks / open items

1. **Kalshi single-game market coverage & ticker format** — must be confirmed by live discovery before crafter output is meaningful. First Kalshi work item.
2. **No historical Kalshi prices** — L2 strategy backtest can't be fully validated until snapshots accumulate; day-one confidence rests on model calibration + forward paper log.
3. **Data leakage** — mitigated by strict as-of features + walk-forward validation + a leakage test.
4. **Market efficiency** — Kalshi prices already aggregate belief; genuine edge is thin. Fee-adjusted edge + quarter Kelly keep us conservative.

## 10. Deferred: player props

Player props are **Phase 2**, specced separately in
`2026-07-09-player-props-feature-spec.md`. The Phase-1 architecture (DuckDB warehouse,
as-of features, crafter/risk gauntlet, snapshotter) is designed so props slot in as a
second model track (`models/props/`) + expanded features without reworking the core.
