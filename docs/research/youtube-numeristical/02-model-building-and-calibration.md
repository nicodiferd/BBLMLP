# Model Building and Calibration — numeristical Baseball Prediction Series

## 1. Source

- **Building the First Model** (video 2) — https://www.youtube.com/watch?v=AARIB6f9c_g
- **Predicting Runs Scored: First Model** (video 11) — https://www.youtube.com/watch?v=rQYtVr1rXIg
- **Nested Models for Total Runs Scored** (video 15) — https://www.youtube.com/watch?v=l1iWisZZWFM

The arc across the three: video 2 trains a direct LightGBM win-probability classifier on aggregate
team hitting stats (OBP/SLG, 30- and 162-game windows), evaluates it with log loss + reliability
diagrams + ICE plots, and beats a naive baseline only modestly (0.683 vs 0.690 log loss). Video 11
pivots from classifying the winner directly to regressing each team's **run-scored distribution**
(hitting vs. opposing pitching) as an intermediate target, reasoning that runs are the causal
mechanism through which hitting quality produces wins. Video 15 combines the two teams' run
distributions with a second-stage **nested model** instead of a naive independence assumption,
then spends most of its runtime diagnosing *why* calibration still breaks down at extreme
predictions — concluding the market (Vegas) embeds information the model lacks, not that the
technique is flawed.

## 2. Techniques worth stealing

**LightGBM early-stopping pattern.** Low learning rate (0.02), high `n_estimators`, a validation-set
callback with patience (stop after 50 rounds with no new low). This removes two hyperparameters
from any grid search and is a direct, low-risk recipe to lift into `models/game/` for the
LightGBM classifier — and into `scratch/winmodel/` now, since that sandbox is explicitly the
staging ground for this model.

**Calibration/reliability-diagram evaluation.** Predicted-probability histogram plus a reliability
diagram with error bars sized by per-bin observation count, read like a hypothesis test ("does
anything here reject good calibration?"). This is verbatim what the design doc's Service 3
selection metric already demands (Brier score + reliability curve over accuracy) — the video is a
working reference implementation of BBLMLP's own stated bar.

**ICE plots as a model-debugging tool.** Per-observation lines showing how a prediction moves as
one feature varies with others held fixed. Video 2's killer example: changing `max_depth` from 2
to 4 left log loss nearly unchanged (0.68299 → 0.68308) but made ICE curves visibly erratic —
proof that a single scalar metric can hide an overfit model. Useful for BBLMLP because Brier/
log-loss is the stated selection metric; ICE plots are the cheap second check that catches what
that metric structurally can't.

**Runs-scored regression as an intermediate target.** Rather than classifying win/loss straight
from aggregate stats, decompose into each team's run distribution (own hitting × opponent
pitching), then combine. This is a physically-motivated alternative feature/model path — not a
replacement for Elo or the direct LightGBM classifier, but a candidate third input.

**Nested/ensemble modeling.** Feed out-of-fold predictions from a first-stage model as features
into a second-stage model, using 5-fold CV **stratified by season** (not randomly) so
near-duplicate games (same matchup days apart) don't leak across folds. Generalizes to stacking
Elo's output as a LightGBM feature.

## 3. Where this maps in BBLMLP

Video 2's chronological 1981-2018 / 2019-2020 / 2021-2022 split **is** BBLMLP's walk-forward-by-date
rule, arrived at independently — direct external validation that "never a random shuffle" is
standard practice for a real backtest, not an idiosyncratic BBLMLP constraint. Worth citing back
against the design doc's own leakage-test requirement (§8).

Video 15's season-stratified-fold nuance sharpens that rule further: walk-forward alone doesn't
prevent near-duplicate leakage between adjacent same-matchup games within a training window — the
leakage test BBLMLP owes itself (§8) should account for this, not just chronological ordering.

The ICE-plot + reliability-diagram pair should be a required artifact of Service 3's model
validation step, not just a Brier number, before any `scratch/winmodel/` prototype gets promoted
into `models/game/`. The early-stopping recipe is a direct lift into that same module.

## 4. Open questions / risks

**Naive feature set.** The videos start from aggregate team OBP/SLG only — explicitly no pitcher
data, rest/travel, or park factors at this stage. BBLMLP's data layer already has Statcast
pitch-level, FanGraphs team/pitcher tables, and standings ingested; there's no reason to replicate
this naive first pass. Go straight to the richer feature families Service 2 already specs (team
form, starting pitcher, context).

**Isotonic calibration is genuinely unprecedented here.** BBLMLP's stated choice is LightGBM +
isotonic calibration fit on a held-out slice. None of the three videos do this — video 2 only
*measures* calibration without correcting it, and video 15's attempt to fix miscalibration via
nested modeling explicitly fails and is reframed as a market-information problem, not a fixable
statistical one. BBLMLP needs its own validation that isotonic regression tightens the reliability
diagram, using a calibration holdout distinct from the early-stopping validation slice.

**Extreme-prediction skepticism.** Video 15's finding — that the model's most extreme predictions
are precisely where the market (Vegas, analogously Kalshi) is right and the model is wrong,
because the market has information the model lacks — is a direct argument for BBLMLP's already-
conservative staking (quarter Kelly, 5%/trade cap, min-confidence 0.55). It also suggests a
concrete enhancement worth testing later: down-weighting or gauntlet-flagging picks where model
probability diverges sharply from the Kalshi-implied price, rather than treating large edges as
the best opportunities by default.
