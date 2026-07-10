import datetime as dt

from bblmlp.ingest.mlb.statsapi_client import month_ranges


def test_month_ranges_splits_season_by_month():
    r = month_ranges("2024-03-01", "2024-11-30")
    assert r[0] == ("2024-03-01", "2024-03-31")
    assert r[1] == ("2024-04-01", "2024-04-30")
    assert r[-1] == ("2024-11-01", "2024-11-30")
    assert len(r) == 9  # Mar..Nov inclusive


def test_month_ranges_contiguous_no_gaps_or_overlaps():
    r = month_ranges("2024-03-01", "2024-11-30")
    for (_s1, e1), (s2, _e2) in zip(r, r[1:]):
        assert dt.date.fromisoformat(s2) == dt.date.fromisoformat(e1) + dt.timedelta(days=1)


def test_month_ranges_single_partial_month():
    assert month_ranges("2024-04-10", "2024-04-20") == [("2024-04-10", "2024-04-20")]


def test_month_ranges_crosses_year_boundary():
    assert month_ranges("2024-12-15", "2025-01-10") == [
        ("2024-12-15", "2024-12-31"),
        ("2025-01-01", "2025-01-10"),
    ]
