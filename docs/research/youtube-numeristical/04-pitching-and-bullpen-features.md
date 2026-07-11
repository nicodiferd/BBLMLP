# Pitching and Bullpen Features (numeristical series, videos 5-8)

## Source

1. [Getting Pitching Data](https://www.youtube.com/watch?v=UXyDeDoeU-Q) (video 5, 41:14)
2. [Add Starting Pitching to Model](https://www.youtube.com/watch?v=nHWA0JO_eA4) (video 6, 45:57)
3. [Create Bullpen Features](https://www.youtube.com/watch?v=9MLy-9HMuP4) (video 7, 17:16)
4. [Add Bullpen Features to Model](https://www.youtube.com/watch?v=og8bBcoL6go) (video 8, 34:52)

The arc: after a hitting-only baseline lost badly to Vegas, the presenter scrapes per-pitcher
game-level logs from Retrosheet (video 5), builds trailing rolling-window features (ERA, WHIP,
K%, an OBP/SLG-style composite) and adds them to the model, closing roughly a third of the
naive-to-Vegas gap (video 6). He then derives bullpen quality by subtracting starter stats from
team-game totals, applies the same rolling-window treatment at team grain (video 7), and adding
those features closes nearly half of what remained — the single biggest jump in the series
(video 8). Throughout, he stress-tests "is this improvement real or noise" with basis-point
framing and Monte Carlo simulation rather than trusting raw log-loss deltas.

## Techniques worth stealing

- **Two-stage pipeline: land raw game logs, then derive as-of rolling features separately.**
  Video 5 builds one row per pitcher-game (IP, ER, H, BB, K, BF) — a plain fact table, no
  windowing. Video 6/8's features are a *second* pass over that table — the same "facts at natural
  grain; rolling/as-of logic is a separate layer" split BBLMLP's ingest design doc already commits to.
- **Aggregate raw counting stats, then compute rates — not the reverse.** ERA35 is
  `sum(ER, last 35 GS) / sum(IP, last 35 GS)`, not `mean(each game's ERA)`. Avoids distortion from
  short outings; the correct pattern for any BBLMLP rolling feature.
- **Partial-window handling via shrinkage, not NaN.** Instead of pandas' default `NaN` until a
  window fills, sum whatever history exists, and for pitchers under a minimum-IP threshold blend
  in a default "replacement-level" value (ERA 5.0) so rookies don't get an overconfident feature.
  Crude — a hardcoded, unjustified constant per the video's own critique — but the shrinkage
  *pattern* is sound.
- **Bullpen-by-subtraction.** No per-reliever tracking; `bullpen_game_stats = team_game_totals −
  starter_stats`, with real nuance in innings (`floor(outs/6)` plus a remainder rule for the
  partial final inning) and batters-faced proxied as `AB + BB + HBP`. The same rolling
  window/shrinkage machinery from starter features is then reapplied at team grain.
- **Multiple window sizes matter more for the bullpen than for starters.** Stacking 10/35/75-game
  windows moved bullpen-feature performance a lot (~22-32 basis points); the same trick on starter
  features barely moved the needle — bullpen composition/usage drifts faster than one starter's
  form, so shorter windows carry more independent signal there.
- **Strict as-of exclusion, verified explicitly in narration:** "the last 10 or 35 games... not
  including that game, because that's the game we're trying to predict." Every rolling feature is
  built by a (pitcher/team, date, doubleheader-seq) lookup that excludes the target game.
- **Model-lift measurement discipline**: basis points (0.0001 log-loss) as a common unit; SHAP for
  feature importance; ICE plots to sanity-check feature *direction*; and, most valuable, a Monte
  Carlo simulation answering "given my test-set size (~3-4k games), how often would a genuinely
  better model still look worse on this one split?" before trusting a 2-10 bp delta.

## Where this maps in BBLMLP

BBLMLP's ingest layer already did the hard part the video spends 40 minutes scraping by hand:
`rollups.py`'s `pitcher_game_stats(pitches)` and `team_game_stats(pitches)` are the deterministic,
this-game-grain fact tables — the analog of video 5's scraped Retrosheet game logs, sourced from
`statcast_pitches` instead of HTML. `pitcher_game_stats` already carries `is_starter`,
`batters_faced`, `k`, `bb`, `whiffs`, `swstr_pct`, and `xwoba_against` — richer, lower-noise
per-batter-faced metrics than the video's ERA/WHIP (the video's own finding that K% beats ERA
because it's "closer to the pitcher's actual impact" is what `xwoba_against`/`swstr_pct` already
give for free).

The **not-yet-built `features/` module** is where video 6/8's second-stage logic belongs: rolling
sum-then-rate aggregation with shrinkage, over `pitcher_game_stats`/`team_game_stats`, keyed by
`(key_mlbam or team, game_date)` and windowed at 10/35/75 games. DuckDB window functions
(`SUM(...) OVER (PARTITION BY pitcher ORDER BY game_date ROWS BETWEEN N PRECEDING AND 1
PRECEDING)`) can replace the video's manual per-pitcher dict-of-DataFrames lookup outright.

One improvement is already available for free: **the bullpen-by-subtraction hack is unnecessary
in BBLMLP.** The video subtracted because Retrosheet only gave team totals and starter lines.
`pitcher_game_stats` has a row for *every* pitcher with `is_starter` flagged — so bullpen-game
stats are just `pitcher_game_stats.filter(is_starter == False).groupby(game_pk, team).sum()`,
exact rather than derived, sidestepping the video's fiddly innings/outs-remainder logic entirely.

The **team-crosswalk gap hits this work directly.** `team_game_stats` carries Statcast's
abbreviation (`SF`); `games`/`standings` carry full team name + numeric `team_id`; FanGraphs'
`team_pitching_season` (bullpen ERA/FIP context, design doc §3.3) carries its own abbreviation
(`SFG`). Any feature that attaches a rolling stat onto a `games` row, or blends Statcast rollups
with FanGraphs team-season context, needs all three keys resolved to one id. Player-level joins
are *not* blocked — the Chadwick crosswalk (`key_mlbam` ↔ `key_fangraphs`) in `players.py` already
bridges starter/reliever identity — but team-grain bullpen aggregation is exactly where the gap
bites, confirming the crosswalk must land before this feature work starts.

## Open questions / risks

**Point-in-time correctness is respected within the video's own technique** — rolling windows are
explicitly built to exclude the target game, computed from pure historical game logs. This
validates BBLMLP's planned approach (`pitcher_game_stats`/`team_game_stats` rollups feeding an
as-of window builder) and should be copied faithfully. Two things need adaptation, not blind copying:

1. **FanGraphs season stats are the trap the video never encounters**, because it never touches
   them — it rebuilds everything from game logs. BBLMLP's design doc already flags (§3.3) that
   FanGraphs season tables are full-season aggregates including future games and must be consumed
   point-in-time; the video's from-scratch approach is effectively existence proof that this is
   the right fix, not a shortcut to skip.
2. **The ERA-5.0 shrinkage constant is arbitrary and era-naive** — a fixed prior across 1980-2022
   ignores that league-average ERA has moved considerably. If BBLMLP adopts shrinkage for
   low-sample pitchers/bullpens, anchor the prior to a rolling league/season average instead, and
   confirm `games`/rollup tables carry a doubleheader sequence — `game_date` alone under-specifies
   ordering on doubleheader days.
