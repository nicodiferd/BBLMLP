# YouTube Research: Baseball Prediction using Machine Learning — Data Wrangling (numeristical, Part 1)

## 1. Source

- **Video**: "Baseball Prediction using Machine Learning - Data Wrangling"
- **Channel**: numeristical
- **Link**: https://www.youtube.com/watch?v=-e5-Ls4yDRs

Part 1 of a multi-part series building an MLB win-probability model from Retrosheet game logs
(1980–2023, ~96k games) toward LightGBM. Covers acquiring Retrosheet CSVs, deriving `home_win`/run
differential, and building trailing 30-game and 162-game rolling hitting stats (AVG/OBP/SLG) per team
as first-pass features, benchmarked against a 53.8% home-win-rate baseline.

## 2. Techniques worth stealing

**a. As-of rolling windows that explicitly exclude the current game.** Each team's games are sorted
chronologically and rolling stats stop *before* the game being predicted — "we don't want to include
the current game." For a betting pipeline this is the whole game: one leaked plate appearance in a
rolling feature inflates backtest ROI and produces a live-vs-paper cliff the first week it matters.

**b. Two window sizes for two timescales.** 30-game (recent form) and 162-game ("true talent")
windows side by side, not one — cheap, and meaningfully different signal: momentum vs.
regression-to-mean anchor.

**c. Home/visitor reshape before computing per-team stats.** Retrosheet stores one row per game with
duplicated `home_*`/`visitor_*` columns; the creator melts each team's games into one chronological
stream, stripping the home/visitor suffix so one rolling function works regardless of which side the
team was on.

**d. Naive baseline before any model.** Compute home-win rate (53.8%) first and treat it as the floor
every feature must beat. For betting the real floor is the market's implied probability net of fees,
not 53.8% — but the habit of anchoring to a naive number before claiming lift should be inherited.

## 3. Where this maps in BBLMLP

- **(a)+(b) → a new `features/` module (not yet built).** This is the concrete gap on CLAUDE.md's
  "Not yet built" list. Given `team_game_stats` (already derived per-game in
  `src/bblmlp/ingest/mlb/rollups.py`), a feature-builder should order rows by
  `(team, game_date, game_pk)` and compute trailing 30-/162-game rolling aggregates excluding the
  current game. In DuckDB that's a `ROWS BETWEEN N PRECEDING AND 1 PRECEDING` window function over
  `team_game_stats`, not a Python loop — a real win over the video, whose own creator computes this
  with an `iterrows()`-style pass he calls inefficient on camera. DuckDB's window functions get
  exclude-current-row correctness for free.

- **(c) is already solved, one layer down.** `rollups.py`'s `_fielding_team`/`_batting_team` helpers
  already do the home/visitor reshape by hand at Statcast pitch grain, producing `team_game_stats`
  (one row per team per game) as the melted output. `features/` should consume `team_game_stats`
  directly rather than re-deriving home/visitor logic against `games`.

- **(d) → `backtest/` (not yet built).** A naive-baseline check (home-win% and
  market-implied-probability-minus-fees floor) belongs in L1 calibration, logged with every backtest
  run, not eyeballed once.

- **Doubleheader disambiguation (date+header-code concatenation) doesn't need porting.** BBLMLP's
  `game_pk` (StatsAPI's own id — `schedule.py`, `games` table in `warehouse.py`) already uniquely
  keys both games of a doubleheader; the video's workaround exists only because Retrosheet's bare date
  field collides.

- **The cross-source team-identity problem the video never faces is already solved.** Retrosheet is
  one self-contained source with no team-id join problem. BBLMLP has three abbreviation schemes to
  reconcile (Statcast, FanGraphs, StatsAPI `team_id`), and — contrary to the "no team crosswalk yet"
  line still in CLAUDE.md's domain rules — `src/bblmlp/ingest/mlb/team_crosswalk.py` already exists
  and is wired into `ingest_all` (`ingest.py` step 6). Nothing to steal; BBLMLP solved a harder
  version of this than the video needed to.

## 4. Open questions / risks

- **Leakage risk to verify, not assume, once BBLMLP writes its own rolling-window code.** The video
  *states* the current game is excluded, but the transcript never shows an explicit shift-before-roll
  step — stated intent isn't proof the code does it. `features/` needs a unit test asserting a
  rolling feature for game N never touches game N's own row, mirroring the design doc's existing
  walk-forward-only rule.

- **This is the concrete answer to the leakage note already on record**, in
  `docs/superpowers/specs/2026-07-09-mlb-data-ingest-comprehensive-design.md` §3.3, which flags
  FanGraphs season tables (full-season aggregates) as needing point-in-time consumption. The video's
  trailing-N-game window — computed over `team_game_stats`, not a season-aggregate row — is that
  substitute: build rolling features from Statcast-derived per-game rollups, and treat FanGraphs
  season stats as prior-season-only context, never a rolling source.

- **No documented policy for insufficient history** (a team's first 30/162 games, or first season in
  the backfill) — the video doesn't resolve this on camera. `features/` needs an explicit, tested
  decision: NaN and let LightGBM route missingness natively, or a warm-up cutoff dropping early-season
  games from training. Separately, era/rule-change mixing across a long backfill (the video's own
  noted survivorship bias) is a walk-forward *validity* question, not a leakage one — worth a
  deliberate call on how many seasons `settings.yaml`'s `backfill_seasons` should span.
