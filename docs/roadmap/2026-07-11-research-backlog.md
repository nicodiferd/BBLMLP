# Post-data-layer roadmap & research-driven backlog

**Date:** 2026-07-11
**Source:** `docs/research/youtube-numeristical/` (six research docs mapping numeristical's
"Baseball Prediction using Machine Learning" series onto BBLMLP), reviewed and decided with Nicolo
in-session.
**Status of decisions:** the three direction calls in §2 are **decided**, not open questions.

This doc is the feeder for future work, not a competing spec. Each issue below graduates to its own
`docs/superpowers/specs/` design (per the repo's superpowers workflow) when picked up; the issue
records why the work matters, what done looks like, and which research doc carries the detail.

---

## 1. Build order

| Step | What | Why this order |
|---|---|---|
| 0a | #1 CLAUDE.md reconcile & commit | already done in working tree; stops stale-doc drift |
| 0b | #2 `live.py` lineup spike | cheap; its outcome sets #7's scope; testable on live games any day |
| 1 | #3 Minimal Kalshi snapshotter | **time-sensitive**: Kalshi serves no price history — every un-snapshotted day of the 2026 season is unrecoverable L2 backtest data |
| 2 | #4–#7 `features/` | biggest model lift per the series (bullpen features were its single largest jump); feeds everything downstream |
| 3 | #8 `models/game/` promotion | needs features; promotion bar per doc 02 |
| 4 | #9–#10 `craft` + Kalshi edge integration | needs model + market data |
| 5 | #11–#12 `backtest/` L1 then L2 | L1 needs the model; L2 needs accrued snapshots |

The deliberate deviation from the design doc's ①→⑤ service numbering is step 1: a *minimal*
`ingest/kalshi/` (data hoarding only, no edge math) jumps the queue because market history only
exists if we record it ourselves (doc 03). Full Kalshi edge integration still lands at step 4 —
`ingest/kalshi/` gets touched twice on purpose.

## 2. Decision record (decided 2026-07-11)

### D1 — Over/under game totals: conditional yes, as a Phase 2.5 rider

Game-total O/U is a genuinely new market type — the player-props spec is per-player only and never
mentions it (doc 06). **Decision:** O/U ships *only* as a derivation from the props spec's planned
Monte-Carlo game-simulation engine, if/when that engine gets built. No standalone totals model,
ever, before that. Any totals derivation must name and test its independence assumption explicitly —
combining two teams' run distributions independently was the series' single biggest documented error
source, larger than the per-team model's own miscalibration (doc 06, video 14).

### D2 — Runs-scored intermediate model: defer with a named trigger

Regressing each team's run distribution (own hitting × opposing pitching) and combining via a nested
second-stage model is physically motivated and would double as the O/U engine foundation (doc 02,
videos 11/15). But the series' own nested version failed to fix extreme-prediction calibration, and
BBLMLP's direct path (Elo → LightGBM + isotonic) is untested against Kalshi yet. **Decision:** not in
`models/game/` v1 scope. Revisit trigger: L1 backtest shows the direct classifier's gap to
Kalshi-implied probabilities has plateaued despite feature work. If the trigger fires and it gets
built, D1's O/U derivation builds on it.

### D3 — Era span: keep 2021–2025, treat the 2023 rule boundary as an eval axis

No backfill earlier than 2021 (2020 COVID season stays excluded). The 2023 pitch clock / shift ban /
bigger bases shifted the run environment mid-window — the series trained across 40 years and shrugged
at era mixing (doc 01); we don't. **Decision:** `models/game/`'s walk-forward eval must compare
training with vs. without pre-2023 seasons (and/or with a rule-era indicator feature) and pick
empirically. Corollary for #6: shrinkage/cold-start priors are trailing per-season values, never
constants averaged across the 2023 boundary.

---

## 3. Step 0 — spikes & housekeeping

### #1 Reconcile & commit CLAUDE.md

**Why:** the research README flagged CLAUDE.md's domain rules as stale ("no team crosswalk yet"
while `team_crosswalk.py` is live in `ingest_all`). The reconciliation pass is **already in the
working tree, uncommitted** — crosswalk domain rule, updated command list, current-status rewrite.
**Done when:** final read-through confirms no remaining stale claims (check "Not yet built" against
`src/bblmlp/`), and the modified CLAUDE.md is committed. *(README, docs 01/04)*

### #2 Verify `live.py` lineup capture (spike)

**Why:** `fetch_today_games` is self-described in-code as a thin, un-unit-tested stub. Lineup
features (#7) only beat team averages on unusual-lineup games (injury/rest/trade) — exactly where a
stub is least likely to be right. Confirmed lineups typically post 1–3h before first pitch. *(doc 05)*
**Done when:** run against a real slate twice — before lineups post and again inside the 1–3h
window — and it's documented whether `{side}_lineup` carries the confirmed starting 9 (with
`batting_order`) pre-first-pitch, or only probables; if not, whether
`statsapi.boxscore_data(game_pk)` enrichment fixes it. Outcome recorded here and in the #7 spec:
either unblocks #7's lineup half or descopes it to probables-only.

## 4. Step 1 — minimal Kalshi snapshotter

### #3 `ingest/kalshi/` snapshot daemon (minimal)

**Why:** Kalshi serves no deep price history; the L2 strategy backtest can only replay data we
snapshotted ourselves. Mid-season, every unbuilt day is lost data. *(doc 03; discovery doc
`docs/kalshi/2026-07-09-kalshi-mlb-market-discovery.md`)*
**Scope:** discovery + recording only. Explicitly **not** in scope: edge math, fees, sizing (step 4).
**Done when:**
- Discovers today's `KXMLBGAME-*` markets and pulls `GET /markets` + `/orderbook` (public, no auth).
- Reads `*_dollars` / `*_fp` fields only (`yes_bid`/`last_price`/`volume` are deprecated-null);
  treats dollar prices as probabilities directly — **no** American-odds conversion, **no** Vegas-style
  vig computation ported.
- Writes timestamped parquet snapshots per pull (CLAUDE.md's mandatory rule), including bid-ask
  spread per market — that plus fees, not "vig," is Kalshi's edge mechanism.
- Maintains a Kalshi-code → StatsAPI `team_id` lookup table (`AZ`, `SD`, `WSH`, …) and joins the
  ticker slug (`{YY}{MMM}{DD}{HHMM}{AWAY}{HOME}` — `HHMM` disambiguates doubleheaders) to
  `games.game_pk`, with a test on a real doubleheader day.
- Runs via a `bblmlp ingest kalshi` CLI command, schedulable (cron/launchd) for multiple pulls/day.

## 5. Step 2 — `features/`

### #4 As-of rolling-window feature builder (team + pitcher grain)

**Why:** the foundational `features/` machinery; the series' entire lift came from trailing-window
features over game-grain fact tables. BBLMLP's fact tables (`team_game_stats`,
`pitcher_game_stats`) already exist via `rollups.py`. *(docs 01, 04)*
**Done when:**
- DuckDB window functions (`SUM(...) OVER (PARTITION BY ... ORDER BY ... ROWS BETWEEN N PRECEDING
  AND 1 PRECEDING)`) — not Python loops — compute trailing windows over the rollup tables.
- Window sizes: 30/162 games at team grain; 10/35/75 at pitcher and bullpen grain (short windows
  carry more independent signal for bullpens — usage drifts faster than one starter's form).
- Rates are computed as `sum(numerator)/sum(denominator)` over the window, never `mean(per-game
  rate)`.
- Ordering key includes a doubleheader disambiguator — `game_date` alone under-specifies
  doubleheader days; use `(game_date, game_pk-derived sequence)` or StatsAPI's doubleheader field.
- **Leakage unit test:** a rolling feature for game N provably never touches game N's own row
  (perturb game N's stats, assert its features don't move).
- FanGraphs season tables are *not* a rolling source — prior-season context only (ingest design doc
  §3.3).

### #5 Bullpen features (exact, not by subtraction)

**Why:** adding bullpen features was the single biggest model improvement in the series — and BBLMLP
gets them *exactly* where the video had to approximate: `pitcher_game_stats` has a row per pitcher
with `is_starter` flagged, so no subtract-starter-from-team-totals hack, no innings/outs remainder
logic. *(doc 04)*
**Done when:** bullpen-game facts = `pitcher_game_stats.filter(is_starter == False).groupby(game_pk,
team)` aggregation; #4's window machinery applied at 10/35/75; features join onto `games` rows via
`team_crosswalk` (never raw abbreviations).

### #6 Cold-start / shrinkage policy

**Why:** partial windows need a deliberate, tested policy, not pandas defaults. The series used
hardcoded priors (ERA 5.0; position baselines eyeballed from the full sample) — the *pattern* is
sound, the constants are era-naive and mildly leaky. *(docs 01, 04, 05)*
**Done when:**
- A written, tested decision between NaN-passthrough (LightGBM handles missingness natively) and
  shrinkage toward a prior — possibly different choices per feature family.
- Any priors are **trailing** league/season values (position-conditioned for batters, league-average
  for pitchers), never static constants, never averaged across the 2023 rule boundary (D3).
- Warm-up handling for the backfill's first season is explicit and tested.

### #7 `batter_game_stats` rollup + lineup features — *blocked by #2*

**Why:** lineup-aggregate features computed from the actual starting 9 close the injury/rest/trade
blind spot of team-season averages. All raw material is ingested (`statcast_pitches` carries
`batter`, `stand`, `events`; Chadwick crosswalk bridges ids) — this is a rollup + join, not a new
source. *(doc 05)*
**Done when:**
- `batter_game_stats` rollup in `rollups.py` (same pattern as pitcher/team), **queryable per player**
  — Phase 2 props reuses it row-per-batter, so don't pre-aggregate away the player grain.
- Trailing windows (30/50/100) via #4's machinery, cold start per #6.
- Lineup features = plain mean of 2–4 rate stats (e.g. OBP/SLG) across the starting 9. The series
  tested per-slot variables (worse) and PA-weighted means (worse) head-to-head — skip both.
- Missing-batter fallback is systematic and logged (adjacent-game stats → position default), never
  silent.
- A starter's position/role on a given day comes from StatsAPI's boxscore field, not career-usage
  heuristics.
- Scope (confirmed lineups vs probables-only) per #2's findings.

## 6. Step 3 — `models/game/`

### #8 Promote `scratch/winmodel` behind a promotion bar

**Why:** the design doc already demands Brier + reliability curves; the series adds the concrete
recipe and one hard-won warning: a hyperparameter change moved log loss 0.68299 → 0.68308 while ICE
plots showed the model visibly more erratic — scalar metrics hide overfit. *(doc 02)*
**Done when:**
- LightGBM uses the early-stopping recipe: low learning rate (~0.02), high `n_estimators`,
  validation callback with ~50-round patience — removes two knobs from any grid search.
- Isotonic calibration is fit on its **own holdout, distinct from the early-stopping slice**, and
  *validated to tighten the reliability diagram* — the series never got calibration correction
  working, so this is unproven, not settled; if isotonic doesn't demonstrably help, don't ship it.
- Required promotion artifacts, alongside Brier/log loss: reliability diagram (error bars sized by
  per-bin count) + ICE plots for the top features.
- Walk-forward by date only (already a hard rule); if Elo output is stacked as a feature, folds are
  **season-stratified** so near-duplicate same-matchup games don't straddle folds.
- Era-boundary comparison per D3 (train with vs. without pre-2023) is part of the eval matrix.

## 7. Step 4 — `craft` + Kalshi edge integration

### #9 Order-book price selection

**Why:** Vegas has one line per side; Kalshi has a full order book. Which price feeds the
fee-adjusted edge calc — best bid, best ask, mid, depth-weighted — is a real design choice the
series never faced, and it directly shifts measured edge (~1% spread on the discovery doc's live
sample). *(doc 03)*
**Done when:** a short written decision (in the step-4 spec) with rationale; the edge calc and the
L2 replay use the same convention; snapshot schema from #3 already captures enough book depth to
revisit.

### #10 Divergence flag in the risk gauntlet — *evidence-gated on #12*

**Why:** the series' late finding: the model's most extreme disagreements with the market are where
the *market* is right — large edges are adversely selected, not the best opportunities. BBLMLP's
gauntlet is already conservative; this adds one more candidate gate. *(docs 02, 03)*
**Done when:** picks where `|model_p − market_p|` exceeds a threshold get flagged/down-weighted —
but only if #12's analysis shows high-divergence picks underperform; if they *outperform*, this
issue closes as won't-do. Don't assume either way.

## 8. Step 5 — `backtest/`

### #11 L1: naive baselines + significance gate

**Why:** anchoring to naive numbers before claiming lift, and refusing to trust small-sample P&L,
are the series' two most transferable habits — it showed a genuine 57.2%-win-rate edge still losing
money 21% of seasons on ~53 bets. *(docs 01, 06)*
**Done when:**
- Every L1 run logs the naive baselines next to model metrics: home-win % and market-implied
  probability net of fees (the real floor, not 53.8%).
- A likelihood-ratio test (`L(alt) / L(null)` binomial) runs on any bet-selection result, re-run
  with a **hostile** alternative (base-rate or midpoint, not the observed rate) — and an L2 P&L
  number is only reported alongside a passing gate.
- Reliability-diagram check of Kalshi's own prices (is the market calibrated?) as a cheap
  sanity/context artifact, mirroring the series' Vegas check.

### #12 L2: divergence classification

**Why:** on Kalshi, a big model-vs-market gap is ambiguous — the model is missing priced-in
information (bad) or the gap *is* the tradeable edge (good). The series treated every gap as a
missing feature; a betting system can't afford that assumption. *(doc 03)*
**Done when:** the L2 replay buckets picks by `|model_p − market_p|` and checks out-of-sample
whether high-divergence picks beat the closing price (from #3's snapshots). Result feeds #10, and
the failure-analysis view (sort by divergence, inspect the largest) becomes a standard L2 artifact.

---

## Explicitly not adopted from the research

- **American-odds conversion & vig-summing** — Vegas-shaped; Kalshi dollar prices are already
  probabilities and `YES ask = $1 − NO bid` by construction (doc 03).
- **Bullpen-by-subtraction, innings-remainder arithmetic** — obsoleted by `is_starter` rows (doc 04).
- **Retrosheet scraping & doubleheader composite-key heuristics** — `game_pk` and Chadwick
  `key_retro` already cover it (docs 01, 05).
- **Per-slot (18-variable) and PA-weighted lineup features** — both lost to the plain mean
  head-to-head (doc 05).
- **Static shrinkage constants** (ERA 5.0, eyeballed position baselines) — pattern kept, constants
  replaced with trailing priors (docs 04, 05).
- **Market prices as model features** — evaluation/benchmark only, never in `features/`; a model
  trained on the market echoes the market and fakes its own edge (doc 03).
