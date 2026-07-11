# Individual Batter Features and Lineup Aggregation — numeristical Baseball Prediction Series

## 1. Source

- **Create Individual Batter Features** (video 9) — https://www.youtube.com/watch?v=Wu15zS5NT6U
- **Add Lineup Features to Model** (video 10) — https://www.youtube.com/watch?v=0WWp8a4m8-k

Video 9 scrapes Retrosheet game-by-game batting logs for ~6,400 players who ever started an MLB
game (1980–2022), computes trailing-window stats (BA/OBP/SLG/OPS/K-rate, 30/50/100-game lookbacks)
per batter as of the game they're about to play, and smooths small-sample players toward
position-specific baselines (pitchers ~.100 BA, C/SS ~.205, 2B/3B ~.240, others ~.255) instead of a
league-wide prior. Video 10 aggregates the nine starters' trailing stats into lineup-level features,
replacing prior team-season averages, for a real but modest and quickly-saturating log-loss gain
(~40bp → ~29bp off Vegas).

## 2. Techniques worth stealing

**Position-conditioned cold-start smoothing.** A low-PA batter is padded toward a position-specific
baseline (role, not raw talent) rather than a global prior — a rookie pitcher's 3 PAs shrink toward
.100, not .255. Same shrinkage-toward-a-prior idea any low-sample BBLMLP feature would want, keyed
on role instead of one flat default.

**Multiple trailing windows computed in parallel** (30/50/100-game), all kept as separate columns
and left for the tree model to select via feature importance rather than hand-picked up front.

**The aggregation step is the most reusable part.** Three variants, evaluated head-to-head under
the same split:
1. **Simple average of OBP/SLG across all 9 starters** — the winner: two features dropped log loss
   ~10bp, more than any other variant.
2. **18 individual position-keyed variables** (batter-1-OBP … batter-9-SLG) — worse despite more
   information, because a greedy tree-splitter can't productively split on "6th-hitter's slugging."
3. **Batting-order-weighted average** (heavier weight on early slots, reasoning they accumulate more
   PAs) — admitted as "not sophisticated," and actually performed *worse* than the unweighted mean.

Start with the plain lineup mean of 2–4 rate stats — it beat every fancier alternative tried,
including the intuitively-appealing PA-weighted version.

**Missing-batter handling is systematic and logged**, not silently imputed: fall back to the
adjacent game's trailing stats, then the position-default baseline (33 of ~96,000×18 slots hit
this).

## 3. Where this maps in BBLMLP

**(a) Phase 1 — team win model.** Lineup-aggregate rate stats over trailing windows are exactly the
"team form" input Service 3 (`features/`, not yet built) needs — computed from actual starters, not
season-to-date team averages, closing the injury/rest/trade blind spot the video calls out. The
data layer is closer to ready than a blank slate:

- `statcast_pitches` already carries `batter` (MLBAM id), `player_name`, `stand`, and `events` per
  pitch — raw material for per-batter game logs already exists, just unrolled up. `rollups.py`
  already does this exact pattern for pitchers/teams (`pitcher_game_stats`/`team_game_stats` from
  `statcast_pitches`); a `batter_game_stats` rollup is the same shape of work.
- The player-id crosswalk is already built: `players.py`'s Chadwick ingest carries `key_mlbam`,
  `key_fangraphs`, `key_bbref`, and **`key_retro`** — so BBLMLP doesn't need Retrosheet scraping at
  all (video 9's whole data-acquisition step); Statcast batter PA outcomes are a point-in-time-safe
  substitute, already joinable to FanGraphs batter tables.
- What's missing is the rollup + lineup join, not a new source: `batter_game_stats` (rollups.py),
  a trailing-window builder (position-conditioned defaults), and a join from each game's starting 9
  (`live.py`, see §4) into 2–4 averaged lineup features per side. Skip the 18-variable and
  PA-weighted variants — go straight to the plain average.

**(b) Phase 2 — player props (deferred).** Yes, plainly: this is the same feature-engineering work
the props spec already lists under "New work when Phase 2 starts" — "batter-vs-pitcher matchup
feature builders in `features/`," "recent form." Video 9's per-batter trailing-stat builder (rolling
windows, role-conditioned cold start, point-in-time as-of joins) *is* that recent-form component,
just consumed differently: Phase 1 averages it across the lineup, Phase 2 feeds each batter's row
individually into the per-prop count model, with `stand` (already in `statcast_pitches`) covering
half the handedness-split requirement for free. Build the per-batter rollup once, queryable per-
player (not pre-aggregated), so Phase 2 reuses it directly.

## 4. Open questions / risks

**Projected-lineup point-in-time availability — BBLMLP's own code already flags this unresolved.**
`live.py`'s `fetch_today_games` is commented "thin stub; enriching real posted lineups may need
`statsapi.boxscore_data(game_pk)` per game to populate `{side}_lineup`. Not unit-tested." The row
shape is right (`batting_order`, `player_id`, `is_probable_pitcher`) but whether it's populated with
the confirmed starting 9 before first pitch, vs. only probable pitchers, is unverified. This is the
highest-leverage gap: the video's whole thesis is that lineup features matter most exactly on the
unusual-lineup games (injury/rest/trade) — if `live.py` can't reliably capture the confirmed lineup
(typically posted 1–3 hours pre-game), the feature degrades toward the team-average baseline it was
built to beat.

**Cold-start defaults under walk-forward discipline.** The video's position baselines are static,
eyeballed once from the full sample. Ported verbatim, they're a mild leakage vector (future league
context informing early-career/early-season padding). Re-derive them as trailing league-wide
position-split rates, not frozen constants.

**Position/role labeling** is ad hoc in the video (career-usage-pattern case handling). BBLMLP
should use StatsAPI's boxscore position field as the source of truth for a starter's role on a
given day instead.
