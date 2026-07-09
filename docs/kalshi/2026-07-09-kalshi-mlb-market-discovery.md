# Kalshi MLB Market Discovery — Findings

**Date:** 2026-07-09
**Purpose:** De-risk Plan 3 (Kalshi integration). Answer the open question: *do single-game MLB markets — and player-prop markets — actually exist on Kalshi, and what are their ticker/market formats?*
**Method:** Unauthenticated reads against the public Kalshi trade API. No account or key required for any of this.

---

## TL;DR (the headline answers)

1. **Yes — single-game MLB markets exist.** The core game series is **`KXMLBGAME`** ("Professional Baseball Game"), a binary market per team (moneyline / game winner). Run line (`KXMLBSPREAD`), total runs (`KXMLBTOTAL`), and first-N-innings variants also exist.
2. **Yes — player-prop markets exist and are live.** HR (`KXMLBHR`), hits (`KXMLBHIT`), strikeouts (`KXMLBKS`), RBIs (`KXMLBRBI`), total bases (`KXMLBTB`), stolen bases (`KXMLBSB`), pitcher outs (`KXMLBOUTS`), H+R+RBI combo (`KXMLBHRR`), and more. Each is a ladder of "N+" threshold contracts per player per game.
3. **⚠️ Breaking API change vs. the old repo.** The legacy price fields (`yes_bid`, `yes_ask`, `last_price`, `volume`, `open_interest` as integer cents/counts) are **deprecated and now return `null`**. The current API uses **`*_dollars`** (dollar-denominated strings, e.g. `"0.5500"`) and **`*_fp`** (fixed-point) fields. **Any old-repo code keyed on the integer fields will silently read `None` and break.** This is the single most important thing to fix before porting anything.
4. **Reads are fully public.** Every call below returned HTTP 200 with **no API key**. Auth is only needed to place/manage orders (live trading).

---

## 1. Host & auth

- **Base URL:** `https://api.elections.kalshi.com/trade-api/v2`
  (All of Kalshi, not just elections, now lives under this host. `api.kalshi.com` / `trading-api.kalshi.com` legacy hosts should be treated as deprecated.)
- **Trailing slash matters:** `GET /series/?...` → `301 Moved Permanently`. Use no trailing slash: `GET /series?...`.
- **Public reads (no auth):** `/series`, `/events`, `/markets`, `/markets/{ticker}`, `/markets/{ticker}/orderbook` — all HTTP 200 unauthenticated. Verified.
- **Auth (RSA-signed, needed later):** only for `/portfolio/*` and order placement in live mode. See §8.

---

## 2. ⚠️ Field-schema change (READ THIS before porting old code)

A single market object from `/markets` now carries these fields (legacy names removed):

| Concept | ❌ Old field (now `null`) | ✅ Current field | Example value |
|---|---|---|---|
| Best YES bid | `yes_bid` | `yes_bid_dollars` | `"0.5400"` |
| Best YES ask | `yes_ask` | `yes_ask_dollars` | `"0.5500"` |
| Best NO bid/ask | `no_bid` / `no_ask` | `no_bid_dollars` / `no_ask_dollars` | `"0.4500"` |
| Last trade | `last_price` | `last_price_dollars` | `"0.5500"` |
| Prev price | `previous_price` | `previous_price_dollars` | — |
| Volume (all-time) | `volume` | `volume_fp` | `15058.98` |
| Volume 24h | `volume_24h` | `volume_24h_fp` | — |
| Open interest | `open_interest` | `open_interest_fp` | `2851507.04` |
| Liquidity | `liquidity` | `liquidity_dollars` | `"0.0000"` |
| Notional | `notional_value` | `notional_value_dollars` | — |
| Bid/ask sizes | — | `yes_bid_size_fp` / `yes_ask_size_fp` | — |

**Notes / open items:**
- `*_dollars` values are **strings** in dollars on a 0.00–1.00 scale (× 100 = cents). Parse as `Decimal`/`float`, don't assume int cents.
- `*_fp` = fixed-point. Values come back with decimals (e.g. `volume_fp=15058.98`, `oi_fp=2851507.04`). **Exact scaling/units should be confirmed against the current API docs before you rely on OI/volume magnitudes** — treat as fixed-point floats for now, not raw contract counts. (Prices via `*_dollars` are unambiguous; the `_fp` volume/OI scaling is the one thing I couldn't pin down purely from the payloads.)
- Other useful fields present: `strike_type`, `floor_strike`, `cap_strike`, `custom_strike`, `result` (`""` while open; `"yes"`/`"no"` when settled), `status` (`active` / `settled`), `open_time`, `close_time`, `rules_primary`, `rules_secondary`.

---

## 3. MLB series catalog (what's on Kalshi)

156 baseball-related series exist. The ones that matter for single-game betting + props:

### Game-level (single game)
| Series | Meaning | Structure |
|---|---|---|
| **`KXMLBGAME`** | Game winner (moneyline) | 2 binary markets/game, one per team |
| **`KXMLBSPREAD`** | Run line | ladder of margin strikes per team |
| **`KXMLBTOTAL`** | Total runs (O/U) | ladder of run-total strikes |
| `KXMLBF5` / `KXMLBF5SPREAD` / `KXMLBF5TOTAL` | First 5 innings winner / spread / total | same shapes, first-5 scope |
| `KXMLBF3`, `KXMLBF7` | First 3 / first 7 innings winner | — |
| `KXMLBRFI` | Run in the 1st inning (yes/no) | — |
| `KXMLBEXTRAS` | Game goes to extra innings | — |

### Player props (per player, per game)
| Series | Prop |
|---|---|
| **`KXMLBHR`** | Home runs (1+, 2+ …) |
| **`KXMLBHIT`** | Hits |
| **`KXMLBKS`** | Pitcher strikeouts (2+ … 8+ …) |
| **`KXMLBRBI`** | RBIs |
| **`KXMLBTB`** | Total bases |
| **`KXMLBSB`** | Stolen bases |
| **`KXMLBOUTS`** | Pitcher outs recorded |
| **`KXMLBHRR`** | Hits + Runs + RBIs combo |
| `KXMLBNEXTHR` | Next home run (in-game) |

### Futures / season-long (NOT single-game — mostly what the old repo's `KXMLB` covered)
`KXMLBWS` (World Series), `KXMLB` (World Series, custom), `KXMLBAL`/`KXMLBNL` (pennants), division winners (`KXMLBALEAST`, `KXMLBNLWEST`, …), `KXMLBWINS-<TEAM>` (season win totals, one series per team), award markets (`KXMLBALMVP`, `KXMLBNLCY`, `KXLEADERMLB*` stat leaders), `KXMLBPLAYOFFS`, `KXMLBBESTRECORD`, etc. Useful later, ignore for the single-game/props MVP.

*(Full 156-row dump is reproducible via the recipe in §7; saved during discovery.)*

---

## 4. Ticker format grammar

### Event ticker
```
KXMLBGAME-26JUL092145COLSF
│         │ │  │ │   │ │
│         │ │  │ │   │ └─ HOME team code  (SF)
│         │ │  │ │   └─── AWAY team code  (COL)
│         │ │  │ └─────── start time HHMM, UTC (2145 = 21:45Z)
│         │ │  └───────── day   (09)
│         │ └──────────── month (JUL)
│         └────────────── year  (26 = 2026)
└──────────────────────── series ticker
```
Format: `{SERIES}-{YY}{MMM}{DD}{HHMM}{AWAY}{HOME}`. The `{YYMMMDDHHMM}{AWAY}{HOME}` slug is shared by **all** market types for that game — e.g. `KXMLBTOTAL-26JUL092145COLSF-…`, `KXMLBKS-26JUL092145COLSF-…` all reference the same COL@SF game. This is the natural join key to line up moneyline + spread + total + props for one game.

### Market ticker by type
| Type | Market ticker | YES means |
|---|---|---|
| Moneyline | `KXMLBGAME-26JUL092145COLSF-SF` | that team (SF) wins |
| Run line | `KXMLBSPREAD-26JUL092145COLSF-SF2` | team wins by > `floor_strike` (SF2 → 1.5) |
| Total | `KXMLBTOTAL-26JUL092145COLSF-9` | total runs > `floor_strike` (9 → 8.5) |
| Player prop | `KXMLBKS-26JUL092145COLSF-COLRFELTNER18-4` | player gets ≥ threshold (Feltner, 4+ K) |

**Rules of thumb:**
- **Do not parse the trailing number as the line.** For spread/total the suffix (`SF2`, `9`) is just a strike **index**; the real line is in **`floor_strike`** + **`strike_type`** (`greater`). Always read those fields.
- Player-prop market ticker = `{event}-{TEAM}{PLAYERCODE}{id}-{THRESHOLD}`, e.g. `COLRFELTNER18-4` = COL + `RFELTNER` + `18` (opaque per-player id — **map it, don't derive it**) + threshold `4` (means "4+"). `yes_sub_title` gives the human label ("Ryan Feltner: 4+").
- Team codes are Kalshi's own abbreviations and include some non-standard ones: **`AZ`** (Arizona, not ARI), `CHC`/`CWS` (Cubs/White Sox), `LAA`/`LAD`, `NYM`/`NYY`, `SD`, `SF`, `TB`, `WSH`, `KC`, `STL`, etc. **Build an explicit team-code map** rather than assuming they match MLB StatsAPI/Retrosheet codes.

---

## 5. Sample slate — COL @ SF, Jul 9 2026 (event `KXMLBGAME-26JUL092145COLSF`)

Live prices captured during discovery (`yes_ask_dollars`), one real game across market types:

**Moneyline** (`KXMLBGAME`)
| Market | Team | Bid | Ask | Last | Vol (fp) |
|---|---|---|---|---|---|
| `…COLSF-SF` | San Francisco | $0.54 | $0.55 | $0.55 | 15,059 |
| `…COLSF-COL` | Colorado | $0.45 | $0.46 | $0.46 | 23,083 |

→ two-sided ≈ $1.01, so ~1% implied vig; deep volume on a same-day game.

**Total runs** (`KXMLBTOTAL`, `strike_type=greater`)
| Market | Line | YES ask (over) | Vol |
|---|---|---|---|
| `…COLSF-9` | Over 8.5 | $0.50 | 6,470 |
| `…COLSF-6` | Over 5.5 | $0.76 | 2,059 |
| `…COLSF-5` | Over 4.5 | $0.87 | 3,355 |

**Run line** (`KXMLBSPREAD`, `strike_type=greater`)
| Market | Line | YES ask | Vol |
|---|---|---|---|
| `…COLSF-SF2` | SF by >1.5 | $0.37 | 4,089 |
| `…COLSF-SF3` | SF by >2.5 | $0.28 | 755 |

**Pitcher strikeouts prop** (`KXMLBKS`, R. Feltner / COL)
| Market | Threshold | YES ask | Vol |
|---|---|---|---|
| `…COLRFELTNER18-2` | 2+ K | $0.91 | — |
| `…COLRFELTNER18-4` | 4+ K | $0.58 | 2,689 |
| `…COLRFELTNER18-6` | 6+ K | $0.21 | 303 |
| `…COLRFELTNER18-8` | 8+ K | $0.06 | 337 |

Monotone ladder (higher threshold → cheaper), exactly as expected.

---

## 6. Orderbook structure

`GET /markets/{ticker}/orderbook?depth=5` returns:
```json
{ "orderbook_fp": {
    "yes_dollars": [ ["0.5100","122.00"], ["0.5200","147.00"], ... ],
    "no_dollars":  [ ["0.3900","6404.00"], ["0.4000","1236.38"], ... ] } }
```
- Two ladders: **`yes_dollars`** = resting YES buy orders, **`no_dollars`** = resting NO buy orders. Each entry is `[price_dollars, size_fp]` (both strings).
- There is no separate "ask" ladder. **YES ask = $1.00 − (best NO bid)**; **NO ask = $1.00 − (best YES bid)**. Standard Kalshi binary convention.
- Top of book here: best YES bid $0.51, best NO bid $0.39 → implied YES ask ≈ $0.61 at snapshot time (moves fast intraday).

---

## 7. Reproduction recipe (copy-paste, no auth)

```bash
BASE="https://api.elections.kalshi.com/trade-api/v2"

# All baseball series (filter client-side for "MLB")
curl -sL "$BASE/series?category=Sports" | jq '.series[] | select(.ticker|test("MLB")) | {ticker,title,frequency}'

# Open single-game moneyline events w/ nested markets
curl -sL "$BASE/events?series_ticker=KXMLBGAME&status=open&with_nested_markets=true&limit=200"

# Live markets for one series (use *_dollars / *_fp fields!)
curl -sL "$BASE/markets?series_ticker=KXMLBGAME&status=open&limit=200"
curl -sL "$BASE/markets?series_ticker=KXMLBHR&status=open&limit=200"     # player HR props
curl -sL "$BASE/markets?series_ticker=KXMLBKS&status=open&limit=200"     # pitcher K props

# All markets for a single game (join key = the shared date+teams slug)
curl -sL "$BASE/markets?event_ticker=KXMLBGAME-26JUL092145COLSF"

# Orderbook
curl -sL "$BASE/markets/KXMLBKS-26JUL092145COLSF-COLRFELTNER18-4/orderbook?depth=10"
```
Pagination: list endpoints accept `limit` (≤ ~1000) and return a `cursor`; pass `&cursor=…` to page.

---

## 8. Account / API-key setup (Plan 3, live mode only — manual, do anytime)

Not needed for any read above. Required only to place orders. Steps:
1. On kalshi.com → Profile → **API Keys** → create a key. Download the **RSA private key** (`.pem`) Kalshi gives you and note the **Key ID** (UUID).
2. Convert to PKCS#8 (what the signing libs expect):
   ```bash
   openssl pkcs8 -topk8 -inform PEM -outform PEM -nocrypt -in key.pem -out key_pkcs8.pem
   ```
3. Store `KALSHI_KEY_ID` (the UUID) + path to `key_pkcs8.pem` as env/secrets. **Do not commit the key** (`.gitignore` already ignores it — verify before adding).
4. Auth = per-request RSA-PSS signature over `timestamp + METHOD + path`, sent as `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-SIGNATURE`, `KALSHI-ACCESS-TIMESTAMP` headers. (Confirm exact header names against current docs when we build the live client.)

**Status:** waiting on the user to create the key + download the `.pem`. Once that file exists I can run the `openssl` conversion and wire up the signer.

---

## 9. Environment prerequisites (Plan 1 Task 1 assumptions) — ✅ verified

| Requirement | Found | OK? |
|---|---|---|
| `uv` installed | `uv 0.11.16` (`~/.local/bin/uv`) | ✅ |
| Python 3.11+ | `Python 3.14.5` (`/opt/homebrew/bin/python3`) | ✅ (well above floor) |

⚠️ Minor: bare **`python`** is not on PATH (only `python3`). If any tooling shells out to `python`, alias it or rely on `uv run`. Python 3.14 is *newer* than the pin — if `pyproject.toml` targets 3.11/3.12, `uv` will fetch the pinned interpreter, so no conflict, just be aware the system default is 3.14.

---

## 10. Recommendations for Plan 3

1. **Port against `*_dollars` / `*_fp`, not the legacy int fields.** Add a thin market-normalizer that reads the new fields and produces `Decimal` prices in [0,1]; fail loudly (not silently to `None`) if a `*_dollars` field is missing.
2. **Model the shared game slug** (`{YYMMMDDHHMM}{AWAY}{HOME}`) as a first-class join key so moneyline/spread/total/props for a game line up, and so Kalshi games can be matched to the MLB StatsAPI schedule (Plan 1 data).
3. **Build explicit maps**: (a) Kalshi team code → MLB team; (b) Kalshi player-prop code (`RFELTNER18`) → MLB player id. Neither is derivable; scrape from `yes_sub_title` + roster.
4. **Confirm two things against live docs before trusting them:** the `_fp` scaling for volume/OI, and the exact live-trading auth header names. Prices via `*_dollars` are safe to use as-is.
5. Player-prop liquidity is real but thinner than moneyline (props: tens–thousands of contracts; moneyline: 15k–23k on a same-day game). Size expectations / slippage models accordingly.

---
*Generated in a parallel session while the main orchestrator builds Plan 1. This file is additive (new `docs/kalshi/` dir) and touches nothing under `src/bblmlp/`, `pyproject.toml`, the DuckDB warehouse, or Plans 1–2/4.*
