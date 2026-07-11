# Market Odds & Edge Evaluation — numeristical videos 3–4

## Source

- **Video 3: "Baseball Prediction using Machine Learning - Getting Odds Data"** — https://www.youtube.com/watch?v=6KOcBbYzTx8
- **Video 4: "Baseball Prediction using Machine Learning - Analyzing Odds Data"** — https://www.youtube.com/watch?v=vKiRZIiXRkA

Video 3 scrapes 2019–2022 moneylines from OddShark, converts American odds to implied probabilities, and joins them onto a 96k-game dataset via a date+doubleheader composite key — reserved for evaluation, never training. Video 4 benchmarks a simple hitting-only LightGBM model against Vegas: measures the naive→Vegas log-loss gap it closes (~33%), checks Vegas's own calibration with a reliability diagram, quantifies vig per game (mostly 1–3%, a second cluster near 4%), and does failure analysis on the largest model/Vegas disagreements — surfacing starting-pitcher quality as the dominant missing feature.

## Techniques worth stealing

**Odds → probability formulas.** Positive line: `100/(100+line)`. Negative line: `|line|/(100+|line|)`. This exists only because sportsbooks quote a payout ratio instead of a price. **Kalshi doesn't have this problem** — `yes_ask_dollars`/`yes_bid_dollars` *is* the probability already, on a $0–$1 scale. No conversion step belongs in `ingest/kalshi/`. This formula only matters if BBLMLP later adds sportsbook odds as a secondary benchmark.

**Vig as a two-sided-sum concept.** The video computes vig as `P(home)+P(away)−100%` from two independently-shaded moneylines. **This does not transfer to Kalshi.** A Kalshi YES/NO pair satisfies `YES ask = $1.00 − NO bid` by construction (discovery doc §6) — there's no independent per-side padding to sum. Kalshi's edge is two separate, more mechanical things: the **bid-ask spread** (discovery doc's live sample: SF ask $0.55 + COL ask $0.46 = $1.01, ~1% spread-implied edge) and the **explicit fee schedule** (`ceil(0.07·C·P·(1−P))` taker / `ceil(0.0175·C·P·(1−P))` maker, already in CLAUDE.md). Compute spread and fees separately — don't back into a Vegas-style "vig %" from Kalshi prices.

**Evaluate-not-train discipline.** The video's strongest methodological point: Vegas odds are held out of the feature set entirely, used only to benchmark log-loss/calibration after the fact. Maps directly to CLAUDE.md's no-leakage rule (point-in-time features, walk-forward validation). Kalshi prices must never become a model *feature* — a model trained on market price just learns to echo the market, making any measured "edge" circular. Kalshi data belongs in `③ project` comparison and `⑤ backtest`, never `features/`.

**Composite-key joining.** The video's doubleheader key (date + inferred game-1/2 ordering) is a heuristic that silently failed at least once (video 3, ~21:05). BBLMLP's join is strictly easier: the Kalshi event slug `{YY}{MMM}{DD}{HHMM}{AWAY}{HOME}` embeds actual UTC start time, so doubleheader legs disambiguate by `HHMM` — no ordering assumption needed. Still requires a Kalshi-code → MLB-team-id map (`AZ`, `SD`, `WSH`, etc.), but that's a fixed lookup table, not a scraped heuristic.

**Per-game vig quantification.** Video 4's best instinct: measure vig *per game* rather than assume a flat number — it finds a bimodal spread (~2% typical, ~4% cluster) and hypothesizes higher spread tracks Vegas's own uncertainty. BBLMLP's fee formula is already per-game and per-price by construction (`P` = live contract price at pull time) — this instinct is already built in.

## Where this maps in BBLMLP

- `ingest/kalshi/`: normalize `*_dollars` fields directly as probabilities; use the ticker slug as the join key to `games.game_pk`; log bid-ask spread per market in each snapshot — that's Kalshi's real edge-mechanism, not a Vegas-style vig.
- `④ craft`: the fee-adjusted-edge math already implements "quantify per-game, don't assume static" — confirmed as correct instinct, no change needed.
- `⑤ backtest` (L1): the reliability-diagram calibration check (bucket predicted P, compare to empirical win rate) is cheap and directly reusable once the game-winner model exists.
- `⑤ backtest` (L2): the failure-analysis pattern — sort by `|model_p − market_p|`, inspect the largest gaps — is useful for strategy debugging, with the caveat below.

**Where BBLMLP is easier:** no HTML scraping, no throttling, no missing-data guesswork (video silently lost 3/96,273 games to unexplained OddShark gaps) — Kalshi is a live, complete, public JSON API. The one genuinely new problem BBLMLP has that the video didn't: Kalshi serves no historical price depth at all, hence the mandatory timestamped-parquet-snapshot requirement to build history forward.

## Open questions / risks

- **Vig-as-static is the video's weakest assumption, not a pattern to copy.** BBLMLP's `P`-dependent fee formula is already more rigorous — the video's finding (vig varies 2–5% by game) validates computing per-game, it doesn't require new code.
- **Divergence ≠ error, on Kalshi.** The video treats every large model/Vegas gap as "my model is missing a feature." On Kalshi that's ambiguous: a persistent divergence could mean BBLMLP is missing priced-in information (bad), or it could be the tradeable edge itself (good). `backtest/` needs a way to distinguish these — e.g. checking whether high-divergence bets beat closing price out-of-sample — before treating divergence-hunting as pure feature-engineering signal.
- **"The" market price isn't single-valued.** Vegas gives one line per side; Kalshi gives a full order book (bid/ask/depth). Which price feeds the edge calc — best bid, best ask, mid, depth-weighted — is an open `④ craft` design choice the video's simpler setup never had to make.
