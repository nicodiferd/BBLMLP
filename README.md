# ⚾ BBLMLP | Baseball ML Prediction 

> An end-to-end ML pipeline that predicts MLB single-game outcomes — practicing leakage-free feature
> engineering and probability calibration, with a public prediction market used as an external
> benchmark for how well-calibrated the model actually is.

## Why I built this

I've studied and played baseball my whole life, and lately I've been getting deeper into data science
and machine learning. This project is my attempt to put that together end-to-end: ingest real
historical data, engineer features the *right* way (no lookahead leakage), train a model that outputs
a genuine probability rather than a hard prediction, and then rigorously check whether that probability
is actually trustworthy. The best resource I've found for the modeling side is a YouTuber named
**[numeristical](https://www.youtube.com/@numeristical)**, who puts out genuinely good content on the
subject.

My original purpose for starting this project came from a conversation I had with one of my close
friends from high school. We've talked about data science, ML algorithms, and prediction models
together, and decided it would be a good idea to build a project of my own around ML and
baseball — since baseball is my sport.

## What it is

A **local Python pipeline** that:

1. **Ingests MLB data** — historical backfill + daily live pulls (schedules, results, Statcast pitch data).
2. **Engineers point-in-time features** — team form and starting-pitcher stats known *before* first pitch (no leakage).
3. **Predicts the winner** — an Elo baseline moving up to a calibrated LightGBM model that outputs `P(home win)`.
4. **Benchmarks calibration against a real market** — compares the model's probability to Kalshi's public
   prediction-market price. A probability is only meaningful if it's calibrated, and a live market price is
   one of the more honest checks available for that.
5. **(Experimental) drafts a paper bet slip** — sizes a hypothetical position with fee-adjusted edge and
   fractional Kelly, purely to see how the model's calibration would translate if acted on. No real
   orders are ever placed.

This is primarily a vehicle for practicing the full ML lifecycle — ingestion, leakage-safe features,
calibrated probabilistic modeling, and walk-forward backtesting — in a domain I know well enough to
sanity-check the model's outputs. The Kalshi comparison is a calibration check, not the goal of the
project.

## How it works

```
ingest MLB  →  as-of features  →  game-winner model  →  calibration check vs Kalshi  →  paper bet slip
(DuckDB)        (no leakage)       (Elo → LightGBM)      (fee-adjusted edge)            (backtest only)
```

**Stack:** Python 3.11 · [uv](https://docs.astral.sh/uv/) · DuckDB · LightGBM + isotonic calibration ·
Typer CLI · `pybaseball` / `MLB-StatsAPI` · Kalshi public REST API.

The whole thing is driven through one `bblmlp` command, and everything reads and writes a single local
DuckDB warehouse.

## Status

**Early / work in progress** — MLB data ingestion is built and tested; feature engineering, the
game-winner model, and Kalshi integration are up next.

## Quickstart

```bash
uv sync                                     # install dependencies
alias bb='PYTHONPATH=src .venv/bin/python -m bblmlp.cli'
bb --help                                   # see available commands
bb init-db                                  # create the local DuckDB warehouse
bb ingest mlb --live                        # pull today's schedule
```

## Disclaimer

This project is for **educational and research purposes** — practicing ML engineering (feature
pipelines, leakage-safe validation, probability calibration) using baseball as the domain. It runs in
paper / backtest mode only, places no real wagers, and is not financial advice.
