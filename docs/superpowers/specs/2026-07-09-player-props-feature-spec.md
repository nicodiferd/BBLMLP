# Feature Spec (Deferred) — Player Props

> Status: **Phase 2 / deferred** · Depends on Phase 1 (`2026-07-09-bblmlp-single-game-betting-design.md`)

Player-prop betting is deferred until the single-game-winner pipeline is working
end-to-end. This spec captures the decisions already made so Phase 2 can start from a
known design instead of re-brainstorming.

## Intent

Predict distributions for MLB **player props** (strikeouts, hits, total bases, runs,
etc.), convert them to over/under probabilities, and feed them through the **same**
edge → Kelly → risk gauntlet → slip crafter used for game winners.

## Design decisions carried over

- **Model family:** **Poisson / Negative-Binomial count models** per prop type (principled
  for discrete counts) → convert modeled distribution to `P(over line)`.
  - Alternative kept in reserve: per-market **quantile regression**.
  - Phase-2 unifier target: a **Monte-Carlo game simulation** engine that produces full
    distributions for any prop *and* game winners from one player-level model.
- **Features:** extend Phase-1 features with **batter-vs-pitcher matchup** data
  (handedness splits, projected plate appearances, recent form), still strictly point-in-time.
- **Selection metric:** Brier / log-loss + calibration on the over/under probability, same
  discipline as Phase 1.

## Hard dependency / gating

- **Kalshi must actually list the prop markets.** Kalshi's MLB **player-prop coverage is
  thin/intermittent** — the Kalshi ingestion service must **inventory available prop
  markets first**; prop modeling only matters for props that are actually tradable.

## Reuses from Phase 1 without change

- DuckDB warehouse + as-of feature discipline.
- Kalshi snapshotter (adds prop-market tickers to the pull).
- `betting/` crafter: fees, fee-adjusted edge, fractional Kelly, risk gauntlet.
- Backtest L1/L2 framework.

## New work when Phase 2 starts

- `models/props/` model track (per prop type).
- Batter-vs-pitcher matchup feature builders in `features/`.
- Prop-market discovery + mapping in `ingest/kalshi/`.
- Prop rows added to the daily slip output.

When Phase 2 begins, run this through the brainstorming → writing-plans flow to turn this
spec into an implementation plan.
