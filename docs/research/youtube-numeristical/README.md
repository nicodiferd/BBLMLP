# Research: numeristical's "Baseball Prediction using Machine Learning" series

Fifteen-video YouTube series (2023) building an MLB win-probability model from scratch — Retrosheet
data wrangling through LightGBM, Vegas odds benchmarking, pitcher/bullpen/batter feature engineering,
edge evaluation, calibration diagnostics, and over/under prediction. Reviewed end-to-end and mapped
onto BBLMLP's actual architecture and roadmap (per `CLAUDE.md` and the specs in
`docs/superpowers/specs/`). Full transcripts + AI summaries of each video live outside this repo, in
the Obsidian vault at `Dev/YouTube-Notes/`, if you want the raw source.

Playlist: https://www.youtube.com/playlist?list=PLeVfk5xTWHYCCqpcNlbRdIXi2CNt9zKvs

## The six docs

| Doc | Videos | Maps to |
|---|---|---|
| [01 — Data wrangling & pipeline design](01-data-wrangling-and-pipeline-design.md) | 1 | `features/` window design, `backtest/` naive-baseline logging |
| [02 — Model building & calibration](02-model-building-and-calibration.md) | 2, 11, 15 | `models/game/` (LightGBM + isotonic calibration) |
| [03 — Market odds & edge evaluation](03-market-odds-and-edge-evaluation.md) | 3, 4 | `ingest/kalshi/`, `④ craft` fee-adjusted edge |
| [04 — Pitching & bullpen features](04-pitching-and-bullpen-features.md) | 5, 6, 7, 8 | `features/`, built on `rollups.py` |
| [05 — Batter & lineup features](05-batter-and-lineup-features.md) | 9, 10 | `features/` (Phase 1) + player-props spec (Phase 2) |
| [06 — Backtesting, calibration & over/under](06-backtesting-calibration-and-overunder.md) | 12, 13, 14 | `backtest/` L1/L2 split |

## Cross-cutting findings worth reading first

**BBLMLP's data layer is further along than `CLAUDE.md`'s "not yet built" framing suggests.**
`team_crosswalk.py` already exists and is wired into `ingest_all`, despite the domain-rules section
still saying "no team crosswalk yet" (docs 01, 04). The Chadwick crosswalk already carries
`key_mlbam`/`key_fangraphs`/`key_retro`, and `statcast_pitches` already has per-pitch batter data —
so most of what the video spends entire episodes scraping (pitcher game logs, batter game logs,
team-id mapping) is either already ingested or a straightforward `rollups.py`-style addition, not new
sourcing (docs 01, 04, 05). **Worth a `CLAUDE.md` pass to reconcile the "Non-obvious domain rules" and
"Not yet built" sections with what's actually landed** — flagged here rather than edited, since that's
your call.

**Vegas concepts don't transfer 1:1 to Kalshi — don't port "vig" as-is.** Kalshi's YES/NO pricing
already satisfies `YES ask = $1.00 − NO bid`, so there's no independent per-side padding to sum the
way Vegas moneylines have. Kalshi's real edge mechanics are bid-ask spread plus the explicit
`taker`/`maker` fee formulas already in `CLAUDE.md` — compute those directly rather than backing into
a Vegas-style vig percentage (doc 03).

**Two concrete, cheap wins for whichever module gets built next:**
- `features/`: bullpen-game stats don't need the video's subtraction-from-team-totals hack —
  `pitcher_game_stats.filter(is_starter == False)` already gives exact per-reliever rows to group and
  sum (doc 04).
- `models/game/`: pair every Brier/log-loss number with an ICE plot before promoting a
  `scratch/winmodel/` prototype — the series has a concrete example of a hyperparameter change that
  left log loss almost unchanged (0.68299 → 0.68308) while making the model visibly more erratic
  underneath (doc 02).

**One real blocker surfaced, not from the videos but from reading BBLMLP's own code against them:**
`live.py`'s `fetch_today_games` is an untested stub and may not capture the confirmed starting lineup
before first pitch. Lineup-level batter features are only valuable on exactly the unusual-lineup games
(injury/rest/trade) this stub is least likely to handle correctly (doc 05) — worth verifying before
investing in lineup features.

**Two ideas outside current scope, worth a deliberate yes/no rather than silent drift:**
- A likelihood-ratio significance test (`L(observed_p) / L(null_p=0.5)`, re-run against a hostile
  alternative hypothesis) as an L1 backtest gate before any L2 P&L number is trusted on a small sample
  (doc 06).
- Game-total (over/under) prediction is a genuinely new market type — not covered by the player-props
  spec, which is per-player only. If the props spec's planned Monte-Carlo game-simulation engine gets
  built, team-total over/under falls out of it almost for free (doc 06).

## Suggested reading order

Given where BBLMLP actually is (data layer built, `features/`/`models/game/`/`ingest/kalshi/`/
`backtest/` all still ahead): **01 → 04 → 05 → 02 → 03 → 06** — pipeline design, then the two feature
families that build directly on existing `rollups.py` output, then modeling, then market data, then
evaluation.
