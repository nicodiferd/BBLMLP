"""Static park reference: physical facts about each MLB park, joinable onto
`games` via `games.venue`.

`games.venue` carries StatsAPI's venue name for every game, including
spring-training/exhibition venues and one-off neutral-site special events
(London Series, Tokyo Series, etc.) that have no bearing on park-factor
modeling. `find_unmapped_venues` filters to regular-season games only, the
same guard `team_crosswalk.py` uses for Statcast abbreviations, so those
~30 spring-training venues never need mapping.

Physical parks are keyed by a stable `park_id`, not by venue name, because
the same park can appear under multiple `games.venue` strings over time
(sponsor renames: Guaranteed Rate Field -> Rate Field in 2025; Minute Maid
Park -> Daikin Park in 2025) -- and a relocation or temporary displacement
must NOT be collapsed the same way, since both venues stay independently
valid (Oakland Coliseum -> Sutter Health Park is a one-way move; Tropicana
Field <-> George M. Steinbrenner Field is a two-way, single-season
displacement, with the Rays back at Tropicana Field in 2026).
`VENUE_NAME_TO_PARK_ID` maps every observed venue string to its park_id;
`PARK_FACTS` holds one row of physical facts per park_id, hand-curated from
public references (Wikipedia ballpark pages, Baseball Reference park pages,
elevation APIs cross-referenced against park coordinates), not fetched.

One-off neutral-site special events (Rickwood Field, London Stadium, Tokyo
Dome, Gocheok Sky Dome, Estadio Alfredo Harp Helu, Bristol Motor Speedway,
BB&T Ballpark, Muncy Bank Ballpark, Journey Bank Ballpark) share
`park_id = "neutral_site"` with NULL facts rather than individually
researched trivia -- real venues, but not worth blocking the pipeline over
1-4 games each.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ParkFacts:
    park_name: str
    altitude_ft: int | None
    roof_type: str | None
    lf_ft: int | None
    cf_ft: int | None
    rf_ft: int | None
    orientation_deg: int | None
    opened_year: int | None


PARK_FACTS: dict[str, ParkFacts] = {
    "american_family_field": ParkFacts(park_name="American Family Field", altitude_ft=630, roof_type="retractable", lf_ft=344, cf_ft=400, rf_ft=345, orientation_deg=135, opened_year=2001),
    "angel_stadium": ParkFacts(park_name="Angel Stadium", altitude_ft=162, roof_type="open", lf_ft=347, cf_ft=396, rf_ft=350, orientation_deg=50, opened_year=1966),
    "busch_stadium": ParkFacts(park_name="Busch Stadium", altitude_ft=443, roof_type="open", lf_ft=336, cf_ft=400, rf_ft=335, orientation_deg=60, opened_year=2006),
    "chase_field": ParkFacts(park_name="Chase Field", altitude_ft=1135, roof_type="retractable", lf_ft=330, cf_ft=407, rf_ft=334, orientation_deg=0, opened_year=1998),
    "citi_field": ParkFacts(park_name="Citi Field", altitude_ft=21, roof_type="open", lf_ft=335, cf_ft=408, rf_ft=330, orientation_deg=35, opened_year=2009),
    "citizens_bank_park": ParkFacts(park_name="Citizens Bank Park", altitude_ft=11, roof_type="open", lf_ft=329, cf_ft=401, rf_ft=330, orientation_deg=18, opened_year=2004),
    "comerica_park": ParkFacts(park_name="Comerica Park", altitude_ft=617, roof_type="open", lf_ft=342, cf_ft=412, rf_ft=330, orientation_deg=145, opened_year=2000),
    "coors_field": ParkFacts(park_name="Coors Field", altitude_ft=5200, roof_type="open", lf_ft=347, cf_ft=415, rf_ft=350, orientation_deg=0, opened_year=1995),
    "daikin_park": ParkFacts(park_name="Daikin Park", altitude_ft=121, roof_type="retractable", lf_ft=315, cf_ft=409, rf_ft=326, orientation_deg=340, opened_year=2000),
    "dodger_stadium": ParkFacts(park_name="Dodger Stadium", altitude_ft=492, roof_type="open", lf_ft=330, cf_ft=395, rf_ft=330, orientation_deg=25, opened_year=1962),
    "fenway_park": ParkFacts(park_name="Fenway Park", altitude_ft=41, roof_type="open", lf_ft=310, cf_ft=390, rf_ft=302, orientation_deg=52, opened_year=1912),
    "globe_life_field": ParkFacts(park_name="Globe Life Field", altitude_ft=569, roof_type="retractable", lf_ft=329, cf_ft=407, rf_ft=326, orientation_deg=46, opened_year=2020),
    "great_american_ball_park": ParkFacts(park_name="Great American Ball Park", altitude_ft=528, roof_type="open", lf_ft=328, cf_ft=404, rf_ft=325, orientation_deg=115, opened_year=2003),
    "rate_field": ParkFacts(park_name="Rate Field", altitude_ft=617, roof_type="open", lf_ft=330, cf_ft=400, rf_ft=335, orientation_deg=120, opened_year=1991),
    "kauffman_stadium": ParkFacts(park_name="Kauffman Stadium", altitude_ft=906, roof_type="open", lf_ft=330, cf_ft=410, rf_ft=330, orientation_deg=48, opened_year=1973),
    "nationals_park": ParkFacts(park_name="Nationals Park", altitude_ft=16, roof_type="open", lf_ft=337, cf_ft=402, rf_ft=335, orientation_deg=30, opened_year=2008),
    "oracle_park": ParkFacts(park_name="Oracle Park", altitude_ft=25, roof_type="open", lf_ft=339, cf_ft=391, rf_ft=309, orientation_deg=87, opened_year=2000),
    "camden_yards": ParkFacts(park_name="Oriole Park at Camden Yards", altitude_ft=20, roof_type="open", lf_ft=333, cf_ft=400, rf_ft=318, orientation_deg=30, opened_year=1992),
    "pnc_park": ParkFacts(park_name="PNC Park", altitude_ft=719, roof_type="open", lf_ft=325, cf_ft=399, rf_ft=320, orientation_deg=120, opened_year=2001),
    "petco_park": ParkFacts(park_name="Petco Park", altitude_ft=16, roof_type="open", lf_ft=336, cf_ft=396, rf_ft=331, orientation_deg=0, opened_year=2004),
    "progressive_field": ParkFacts(park_name="Progressive Field", altitude_ft=681, roof_type="open", lf_ft=325, cf_ft=400, rf_ft=325, orientation_deg=356, opened_year=1994),
    "rogers_centre": ParkFacts(park_name="Rogers Centre", altitude_ft=299, roof_type="retractable", lf_ft=328, cf_ft=400, rf_ft=328, orientation_deg=0, opened_year=1989),
    "sutter_health_park": ParkFacts(park_name="Sutter Health Park", altitude_ft=31, roof_type="open", lf_ft=330, cf_ft=403, rf_ft=325, orientation_deg=65, opened_year=2000),
    "t_mobile_park": ParkFacts(park_name="T-Mobile Park", altitude_ft=39, roof_type="retractable", lf_ft=331, cf_ft=401, rf_ft=326, orientation_deg=45, opened_year=1999),
    "target_field": ParkFacts(park_name="Target Field", altitude_ft=828, roof_type="open", lf_ft=339, cf_ft=404, rf_ft=328, orientation_deg=90, opened_year=2010),
    "tropicana_field": ParkFacts(park_name="Tropicana Field", altitude_ft=115, roof_type="fixed_dome", lf_ft=315, cf_ft=404, rf_ft=322, orientation_deg=60, opened_year=1990),
    "truist_park": ParkFacts(park_name="Truist Park", altitude_ft=1025, roof_type="open", lf_ft=335, cf_ft=400, rf_ft=325, orientation_deg=135, opened_year=2017),
    "wrigley_field": ParkFacts(park_name="Wrigley Field", altitude_ft=602, roof_type="open", lf_ft=355, cf_ft=400, rf_ft=353, orientation_deg=30, opened_year=1914),
    "yankee_stadium": ParkFacts(park_name="Yankee Stadium", altitude_ft=26, roof_type="open", lf_ft=318, cf_ft=408, rf_ft=314, orientation_deg=55, opened_year=2009),
    "loandepot_park": ParkFacts(park_name="loanDepot park", altitude_ft=26, roof_type="retractable", lf_ft=344, cf_ft=400, rf_ft=335, orientation_deg=135, opened_year=2012),
    "oakland_coliseum": ParkFacts(park_name="Oakland Coliseum", altitude_ft=20, roof_type="open", lf_ft=330, cf_ft=400, rf_ft=330, orientation_deg=60, opened_year=1966),
    "sahlen_field": ParkFacts(park_name="Sahlen Field", altitude_ft=618, roof_type="open", lf_ft=325, cf_ft=404, rf_ft=325, orientation_deg=158, opened_year=1988),
    "td_ballpark": ParkFacts(park_name="TD Ballpark", altitude_ft=23, roof_type="open", lf_ft=333, cf_ft=400, rf_ft=336, orientation_deg=135, opened_year=1990),
    "steinbrenner_field": ParkFacts(park_name="George M. Steinbrenner Field", altitude_ft=46, roof_type="open", lf_ft=318, cf_ft=408, rf_ft=314, orientation_deg=60, opened_year=1996),
    "neutral_site": ParkFacts(park_name="Neutral site (one-off special event)", altitude_ft=None, roof_type=None, lf_ft=None, cf_ft=None, rf_ft=None, orientation_deg=None, opened_year=None),
}

VENUE_NAME_TO_PARK_ID: dict[str, str] = {
    "American Family Field": "american_family_field",
    "Angel Stadium": "angel_stadium",
    "Busch Stadium": "busch_stadium",
    "Chase Field": "chase_field",
    "Citi Field": "citi_field",
    "Citizens Bank Park": "citizens_bank_park",
    "Comerica Park": "comerica_park",
    "Coors Field": "coors_field",
    "Minute Maid Park": "daikin_park",
    "Daikin Park": "daikin_park",
    "Dodger Stadium": "dodger_stadium",
    "Fenway Park": "fenway_park",
    "Globe Life Field": "globe_life_field",
    "Great American Ball Park": "great_american_ball_park",
    "Guaranteed Rate Field": "rate_field",
    "Rate Field": "rate_field",
    "Kauffman Stadium": "kauffman_stadium",
    "Nationals Park": "nationals_park",
    "Oracle Park": "oracle_park",
    "Oriole Park at Camden Yards": "camden_yards",
    "PNC Park": "pnc_park",
    "Petco Park": "petco_park",
    "Progressive Field": "progressive_field",
    "Rogers Centre": "rogers_centre",
    "Sutter Health Park": "sutter_health_park",
    "T-Mobile Park": "t_mobile_park",
    "Target Field": "target_field",
    "Tropicana Field": "tropicana_field",
    "Truist Park": "truist_park",
    "Wrigley Field": "wrigley_field",
    "Yankee Stadium": "yankee_stadium",
    "loanDepot park": "loandepot_park",
    "Oakland Coliseum": "oakland_coliseum",
    "Sahlen Field": "sahlen_field",
    "TD Ballpark": "td_ballpark",
    "George M. Steinbrenner Field": "steinbrenner_field",
    # One-off neutral-site special events (<=4 games each) -- see module docstring.
    "BB&T Ballpark": "neutral_site",
    "Bristol Motor Speedway": "neutral_site",
    "Estadio Alfredo Harp Helu": "neutral_site",
    "Gocheok Sky Dome": "neutral_site",
    "Journey Bank Ballpark": "neutral_site",
    "London Stadium": "neutral_site",
    "Muncy Bank Ballpark": "neutral_site",
    "Rickwood Field": "neutral_site",
    "Tokyo Dome": "neutral_site",
}

_OUTPUT_COLUMNS = [
    "venue", "park_id", "park_name", "altitude_ft", "roof_type",
    "lf_ft", "cf_ft", "rf_ft", "orientation_deg", "opened_year",
]


def find_unmapped_venues(games: pd.DataFrame) -> set[str]:
    """Distinct regular-season venue strings not present in VENUE_NAME_TO_PARK_ID.

    Filters to game_type == 'R' (spring-training/exhibition venues are noise,
    the same guard team_crosswalk.py uses for Statcast abbreviations) and
    drops NULL venue rows (a known, separately-tracked data-quality gap, not
    a new venue to map).
    """
    regular = games[games["game_type"] == "R"]
    venues = set(regular["venue"].dropna().unique())
    return venues - set(VENUE_NAME_TO_PARK_ID.keys())


def build_park_reference(games: pd.DataFrame) -> pd.DataFrame:
    """One row per distinct regular-season venue: park_id + PARK_FACTS joined.

    Raises ValueError if a venue in `games` isn't in VENUE_NAME_TO_PARK_ID --
    likely a new venue, sponsor rename, or relocation; the message names the
    venue and points at the fix (mirrors team_crosswalk.py's error style).
    """
    unmapped = find_unmapped_venues(games)
    if unmapped:
        raise ValueError(
            f"Unmapped venue(s) found in regular-season games: {sorted(unmapped)}. "
            "Likely a new venue, sponsor rename, or relocation -- add an entry to "
            "VENUE_NAME_TO_PARK_ID (and PARK_FACTS if it's a genuinely new park)."
        )
    regular = games[games["game_type"] == "R"]
    venues = sorted(regular["venue"].dropna().unique())
    rows = []
    for venue in venues:
        park_id = VENUE_NAME_TO_PARK_ID[venue]
        facts = PARK_FACTS[park_id]
        rows.append({
            "venue": venue,
            "park_id": park_id,
            "park_name": facts.park_name,
            "altitude_ft": facts.altitude_ft,
            "roof_type": facts.roof_type,
            "lf_ft": facts.lf_ft,
            "cf_ft": facts.cf_ft,
            "rf_ft": facts.rf_ft,
            "orientation_deg": facts.orientation_deg,
            "opened_year": facts.opened_year,
        })
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS)
