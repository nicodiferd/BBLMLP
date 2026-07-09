# ⚾ BBLMLP | Baseball ML Prediction 

> A model that predicts MLB single-game outcomes and looks for value against Kalshi's money-line markets.

## Why I built this

I wanted to make this project because I've always been interested in baseball, and lately in baseball
machine learning prediction. I've studied and played baseball for my entire life, and now that I'm
getting deeper into data science, machine learning, and AI, this felt like a good opportunity to take
what I know about ML models and try to build something that can predict games well enough to have a
winning percentage against sports odds. We're starting with **money line only** and will move into
**player props** later. The best resource I've found online so far is a YouTuber named
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
4. **Finds value on Kalshi** — compares the model's probability to the market price, adjusts for fees, and sizes any bet with fractional (quarter) Kelly.
5. **Outputs a bet slip** — a daily list of picks with model probability, market price, edge, stake, and expected value.

Everything runs on my own machine in **paper / backtest mode** — the pipeline recommends bets, it does
not place them.

## How it works

```
ingest MLB  →  as-of features  →  game-winner model  →  compare to Kalshi  →  craft bet slip
(DuckDB)        (no leakage)       (Elo → LightGBM)      (fee-adjusted edge)   (quarter-Kelly)
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
uv sync                          # install dependencies
uv run bblmlp --help             # see available commands
uv run bblmlp init-db            # create the local DuckDB warehouse
uv run bblmlp ingest mlb --live  # pull today's schedule
```

## Disclaimer

This project is for **educational and research purposes**. It runs in paper / backtest mode, does not
place real wagers, and is not financial advice. Sports betting carries real financial risk — bet
responsibly
