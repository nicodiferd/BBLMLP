from pathlib import Path

from bblmlp.config import load_settings


def test_load_settings_parses_data_section():
    s = load_settings("tests/fixtures/settings_min.yaml")
    assert s.data.warehouse_path == Path("/tmp/bblmlp_test.duckdb")
    assert s.data.backfill_seasons == [2024, 2025]


def test_extra_top_level_sections_are_allowed():
    # later plans add kalshi/model/staking sections; loader must not reject them
    import tempfile

    text = (
        "data:\n"
        "  warehouse_path: a.duckdb\n"
        "  snapshot_dir: snaps\n"
        "  backfill_seasons: [2025]\n"
        "future_section:\n"
        "  anything: true\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(text)
        p = f.name
    s = load_settings(p)
    assert s.data.backfill_seasons == [2025]
