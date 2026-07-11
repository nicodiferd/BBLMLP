# Backtesting, Calibration, and Over/Under — numeristical videos 12–14

## Source

- **Video 12: "Predicting the Over/Under"** — https://www.youtube.com/watch?v=v6qjNxZcJ_Y
- **Video 13: "Evaluating our Edge"** — https://www.youtube.com/watch?v=FBWf2MzdJRA
- **Video 14: "Examine Calibration of Runs Scored"** — https://www.youtube.com/watch?v=rquWdHUq45k

Video 12 combines two per-team runs-scored distributions into a game-total distribution via an
independence assumption, derives over/under/push probabilities, and backtests threshold-based
betting against a flat -110 line on ~2,100 games — profitable at high thresholds but with weak
likelihood-ratio evidence (4.5–9x). Video 13 repeats the analysis on 16,358 games (2019–2022) to
get a much stronger ratio (38:1) that the edge is real, then Monte-Carlo simulates a season of
betting to show a genuine 57.2%-win-rate edge still carries a 21% chance of losing money in a
single season on ~53 bets. Video 14 diagnoses why the model claimed ~70% confidence but only hit
57%, using reliability diagrams, class-by-class binary calibration across 17 run-count classes,
and season-by-season variance — concluding the per-team runs model is only mildly miscalibrated,
and the independence assumption combining the two team distributions is the likelier dominant
error source.

## Techniques worth stealing

**Edge quantification via likelihood ratio, not raw win rate.** Given `wins`/`losses` on the bets
a threshold selected, the video computes `L(alt_p) / L(null_p=0.5)` under a binomial model, using
the observed win rate as the alternative hypothesis, then stress-tests by substituting a *less*
favorable alternative (an "always bet the under" base rate, or the midpoint between null and
observed) — the edge survives (38 → 19 → 9). "Pick a favorable number, then re-run with a hostile
number" is a cheap, reusable significance check for a small-sample backtest result.

**Calibration diagnostics for a regression/multiclass target, not just a binary classifier.** The
runs-scored model outputs a 17-way distribution (0–16+ runs), so one reliability diagram isn't
enough. Three techniques combine: (1) random single-class sampling per game to get independent
binary observations for a reliability diagram, repeated across seeds for stability; (2) one-vs-rest
binary calibration per class, looking for several classes in a row biased the same direction — far
stronger evidence than any one class alone; (3) mean-predicted vs. mean-actual ratio per class,
checked against that class's own season-to-season variance (low-run frequency alone swings 49–62%
across seasons) — a gap inside normal seasonal drift is noise, not a calibration bug.

**Over/under as a derived, not independently-trained, task.** The video never trains on the
over/under label directly. It trains one runs-scored distribution model per team-vs-opposing-
pitchers matchup, then combines the two per game via discrete convolution (with explicit
integer-vs-half-point-line handling for push probability) into `P(over)/P(under)/P(push)`. One
model family feeds two markets — flagged as a future step to also feed the moneyline model.

## Where this maps in BBLMLP

**(a) L1 vs. L2.** The video's "evaluate our edge" is a hybrid BBLMLP's design splits apart on
purpose. Threshold selection, win/loss counting, and profit simulation is strategy replay — **L2**
— but approximated with a flat -110 line instead of real market prices, exactly the gap Kalshi
snapshotting (CLAUDE.md's mandatory timestamped-parquet rule) exists to close. The likelihood-ratio
test and Monte-Carlo variance simulation ask a different question — "is this result signal or
noise" *before* trusting any P&L — which belongs in **L1**, or as a precondition L1 clears before
an L2 result is trusted. `backtest/` should add a likelihood-ratio (or equivalent binomial) test to
L1; Brier/log-loss alone don't answer that for a small sample.

**(b) Fee-adjusted edge is a real refinement the video skips.** It assumes a flat -110 line for
every game/threshold. BBLMLP's fee formula (`ceil(0.07·C·P·(1−P))` taker /
`ceil(0.0175·C·P·(1−P))` maker) is price-dependent, maximized near P=0.5 and shrinking near the
tails — same spirit as the video's own vig complaint but computed per-trade instead of assumed
constant. When `betting/` is built, don't borrow the video's flat-profit arithmetic — BBLMLP
already specifies the more correct formula.

**(c) Over/under is a genuinely new market type, not in the player-props spec.** That spec covers
*per-player* props (strikeouts, hits, total bases) via Poisson/NB count models — it never mentions
team/game-level total-runs over/under, which is what these videos build. Kalshi's moneyline ticker
is the only market type in Phase 1 scope. Worth flagging as a possible Phase 2/2.5 extension
alongside player props — the video's two-team convolution is a rougher version of the "Monte-Carlo
game simulation engine" the player-props spec already names as its Phase-2 unifier target; if
BBLMLP builds that unifier, team-total-runs O/U falls out almost for free.

## Open questions / risks

**BBLMLP's risk gauntlet is intentionally stricter than anything shown here — confirmation, not a
gap.** The video bets down to a 0.05 edge with flat sizing, no confidence floor, no drawdown halt,
no quarter-Kelly — and still shows a 21% chance of a losing season with a genuine edge. CLAUDE.md's
gauntlet (min-confidence 0.55 → positive Kelly → drawdown halt 20% → daily-loss limit → 5%/trade
cap, on top of quarter Kelly) cuts both bet frequency and size relative to the video's strategy, by
design.

**The regression-calibration method (video 14) is directly reusable once BBLMLP has a runs model.**
Phase 1's game-winner is a binary classifier, not a regressor, but if a future totals feature adds
one, the three-pronged diagnostic above — sampled reliability diagrams, one-vs-rest per-class
calibration, mean-predicted-vs-actual checked against season variance — is a ready-made L1
evaluation recipe, more informative than Brier score alone for a count target.

**Independence-assumption risk transfers directly.** Video 14's conclusion — combining two
marginal distributions independently is the *larger* error source, bigger than the per-team
model's own miscalibration — warns against any future BBLMLP feature combining two team-level
outputs (a totals market, home/away interactions). If independence is used as a shortcut, name it
as a known approximation with a plan to test/replace it, not leave it implicit.
