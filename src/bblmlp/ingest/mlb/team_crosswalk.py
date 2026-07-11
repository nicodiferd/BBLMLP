"""Team-id crosswalk: reconciles team identity across MLB data sources.

`games`/`standings` key teams by MLB-StatsAPI's numeric `team_id` (stable across
seasons — the anchor). `statcast_pitches` uses Statcast's own abbreviation, and
FanGraphs team tables use FanGraphs' abbreviation; neither matches the other,
and FanGraphs' abbreviation can itself change season-to-season on relocation
(e.g. the Athletics: FanGraphs `OAK` through 2024, `ATH` from 2025 on, after
the move to Sacramento — Statcast already reports `ATH` retroactively for every
season). Statcast's abbreviation is derived here directly from a `game_pk` join
(self-updating, no maintenance); FanGraphs' has no shared join key with
`games`/`standings`, so it needs a small hand-maintained base map plus
season-scoped overrides for known relocations/renames — validated against the
real ingested FanGraphs data so undetected drift raises instead of silently
mis-joining.
"""
from __future__ import annotations

import pandas as pd

# MLB-StatsAPI numeric team_id -> FanGraphs team abbreviation (as of the most
# recent season with no override below). These ids are stable identifiers for
# the franchise, unlike display name or abbreviation.
FANGRAPHS_ABBR_BY_TEAM_ID: dict[int, str] = {
    108: "LAA", 109: "ARI", 110: "BAL", 111: "BOS", 112: "CHC",
    113: "CIN", 114: "CLE", 115: "COL", 116: "DET", 117: "HOU",
    118: "KCR", 119: "LAD", 120: "WSN", 121: "NYM", 133: "OAK",
    134: "PIT", 135: "SDP", 136: "SEA", 137: "SFG", 138: "STL",
    139: "TBR", 140: "TEX", 141: "TOR", 142: "MIN", 143: "PHI",
    144: "ATL", 145: "CHW", 146: "MIA", 147: "NYY", 158: "MIL",
}

# (team_id, from_season) -> abbreviation, effective from `from_season` onward
# until superseded by a later override for the same team_id.
FANGRAPHS_ABBR_OVERRIDES: list[tuple[int, int, str]] = [
    (133, 2025, "ATH"),  # Athletics relocated Oakland -> Sacramento for 2025.
]


def _fangraphs_abbr_for(team_id: int, season: int) -> str:
    abbr = FANGRAPHS_ABBR_BY_TEAM_ID[team_id]
    applicable = [o for o in FANGRAPHS_ABBR_OVERRIDES if o[0] == team_id and o[1] <= season]
    if applicable:
        abbr = max(applicable, key=lambda o: o[1])[2]
    return abbr


def _derive_statcast_abbr(games: pd.DataFrame, statcast_pitches: pd.DataFrame) -> pd.DataFrame:
    reg = games[games["game_type"] == "R"][["game_pk", "season", "home_team_id", "away_team_id"]]
    sc_games = statcast_pitches[["game_pk", "home_team", "away_team"]].drop_duplicates()
    merged = reg.merge(sc_games, on="game_pk", how="inner")

    home = merged[["season", "home_team_id", "home_team"]].rename(
        columns={"home_team_id": "team_id", "home_team": "statcast_abbr"}
    )
    away = merged[["season", "away_team_id", "away_team"]].rename(
        columns={"away_team_id": "team_id", "away_team": "statcast_abbr"}
    )
    pairs = pd.concat([home, away], ignore_index=True)
    mode = pairs.groupby(["season", "team_id"])["statcast_abbr"].agg(lambda s: s.mode().iat[0])
    return mode.reset_index()


def build_team_crosswalk(
    standings: pd.DataFrame,
    games: pd.DataFrame,
    statcast_pitches: pd.DataFrame,
    fangraphs_team: pd.DataFrame,
) -> pd.DataFrame:
    """Build one row per (team_id, season): team_name, statcast_abbr, fangraphs_abbr.

    `standings` anchors identity (season, team_id, team_name — one row per team
    per season). `statcast_abbr` is derived from a `games` x `statcast_pitches`
    join on `game_pk`, restricted to regular-season games so exhibition/spring
    opponents outside the 30-team universe can't pollute the mode. `fangraphs_abbr`
    comes from the static map above and is validated against `fangraphs_team`'s
    actually-ingested abbreviations for seasons present there.
    """
    anchor = standings[["season", "team_id", "team_name"]].drop_duplicates()

    statcast_abbr = _derive_statcast_abbr(games, statcast_pitches)
    out = anchor.merge(statcast_abbr, on=["season", "team_id"], how="left")

    ingested_by_season = (
        fangraphs_team.groupby("season")["team"].apply(set).to_dict()
    )

    fg_abbrs = []
    for team_id, season in zip(out["team_id"], out["season"]):
        expected = _fangraphs_abbr_for(team_id, season)
        actual = ingested_by_season.get(season)
        if actual is not None and expected not in actual:
            raise ValueError(
                f"team_id={team_id} season={season}: expected FanGraphs abbreviation "
                f"'{expected}' not found in ingested data ({sorted(actual)}). "
                "The team likely renamed/relocated — add a FANGRAPHS_ABBR_OVERRIDES entry."
            )
        fg_abbrs.append(expected)
    out["fangraphs_abbr"] = fg_abbrs

    return out.reset_index(drop=True)
