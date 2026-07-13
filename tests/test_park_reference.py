import pandas as pd
import pytest

from bblmlp.ingest.mlb.park_reference import (
    PARK_FACTS,
    VENUE_NAME_TO_PARK_ID,
    build_park_reference,
    find_unmapped_venues,
)


def _games(rows):
    return pd.DataFrame(rows, columns=["game_pk", "game_type", "venue"])


def test_find_unmapped_venues_ignores_non_regular_season_and_null_venue():
    games = _games([
        (1, "R", "Dodger Stadium"),      # mapped, regular season
        (2, "S", "Some Spring Complex"),  # unmapped, but spring training -> ignored
        (3, "R", None),                   # NULL venue, regular season -> ignored (known gap)
    ])
    assert find_unmapped_venues(games) == set()


def test_find_unmapped_venues_flags_unmapped_regular_season_venue():
    games = _games([
        (1, "R", "Dodger Stadium"),   # mapped
        (2, "R", "Some New Stadium"),  # unmapped, regular season -> flagged
    ])
    assert find_unmapped_venues(games) == {"Some New Stadium"}


def test_build_park_reference_produces_one_row_per_distinct_venue_with_facts():
    games = _games([
        (1, "R", "Dodger Stadium"),
        (2, "R", "Dodger Stadium"),  # same venue, second game -> still one row
        (3, "R", "Petco Park"),
    ])
    out = build_park_reference(games)
    assert len(out) == 2
    row = out[out["venue"] == "Dodger Stadium"].iloc[0]
    assert row["park_id"] == "dodger_stadium"
    assert row["altitude_ft"] == 492
    assert row["roof_type"] == "open"


def test_build_park_reference_resolves_sponsor_rename_to_same_park_id():
    games = _games([
        (1, "R", "Guaranteed Rate Field"),
        (2, "R", "Rate Field"),
    ])
    out = build_park_reference(games)
    assert set(out["park_id"]) == {"rate_field"}
    assert len(out) == 2  # two distinct venue strings, same park_id


def test_build_park_reference_treats_relocation_as_distinct_park_ids():
    # Oakland Coliseum (Athletics, 2021-2024) and Sutter Health Park (2025+)
    # are physically different parks -- must NOT collapse to one park_id
    # the way a sponsor rename does.
    games = _games([
        (1, "R", "Oakland Coliseum"),
        (2, "R", "Sutter Health Park"),
    ])
    out = build_park_reference(games)
    assert set(out["park_id"]) == {"oakland_coliseum", "sutter_health_park"}


def test_build_park_reference_treats_two_way_displacement_as_distinct_park_ids():
    # Tropicana Field and George M. Steinbrenner Field (Rays, 2025 only) are
    # both still valid -- Rays returned to Tropicana Field in 2026.
    games = _games([
        (1, "R", "Tropicana Field"),
        (2, "R", "George M. Steinbrenner Field"),
    ])
    out = build_park_reference(games)
    assert set(out["park_id"]) == {"tropicana_field", "steinbrenner_field"}


def test_neutral_site_venues_get_null_facts():
    games = _games([(1, "R", "Tokyo Dome")])
    out = build_park_reference(games)
    row = out.iloc[0]
    assert row["park_id"] == "neutral_site"
    assert pd.isna(row["altitude_ft"])
    assert pd.isna(row["roof_type"])


def test_build_park_reference_raises_on_unmapped_venue():
    games = _games([(1, "R", "Some New Stadium")])
    with pytest.raises(ValueError, match="Some New Stadium"):
        build_park_reference(games)


def test_every_venue_maps_to_a_defined_park_id():
    for venue, park_id in VENUE_NAME_TO_PARK_ID.items():
        assert park_id in PARK_FACTS, f"{venue!r} maps to undefined park_id {park_id!r}"


def test_park_facts_and_venue_map_counts():
    # 34 real parks + 1 neutral_site catch-all
    assert len(PARK_FACTS) == 35
    # 36 real venue strings (incl. 2 sponsor-rename pairs) + 9 neutral-site venues
    assert len(VENUE_NAME_TO_PARK_ID) == 45
