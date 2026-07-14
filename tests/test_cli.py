from typer.testing import CliRunner

from bblmlp.cli import app

runner = CliRunner()


def test_version_command_prints_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_ingest_group_exists():
    result = runner.invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0


def test_build_group_has_park_reference_command():
    result = runner.invoke(app, ["build", "--help"])
    assert result.exit_code == 0
    assert "park-reference" in result.stdout


def _game_row(venue: str) -> dict:
    return {
        "game_pk": 1, "season": 2025, "game_type": "R", "game_date": "2025-07-04",
        "game_datetime": "2025-07-04T18:05:00Z", "home_team": "Dodgers", "away_team": "Giants",
        "home_team_id": 119, "away_team_id": 137,
        "home_probable_pitcher": None, "away_probable_pitcher": None,
        "home_probable_pitcher_id": None, "away_probable_pitcher_id": None,
        "venue": venue, "status": "Final", "home_score": 5, "away_score": 3, "home_win": 1,
    }


def test_check_group_has_venues_command():
    result = runner.invoke(app, ["check", "--help"])
    assert result.exit_code == 0
    assert "venues" in result.stdout


def test_check_venues_exits_zero_when_all_mapped(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from bblmlp.storage import connect, init_schema, upsert_games

    warehouse = tmp_path / "w.duckdb"
    con = connect(warehouse)
    init_schema(con)
    upsert_games(con, [_game_row("Dodger Stadium")])
    con.close()

    fake_settings = SimpleNamespace(data=SimpleNamespace(warehouse_path=warehouse))
    monkeypatch.setattr("bblmlp.config.load_settings", lambda *a, **k: fake_settings)

    result = runner.invoke(app, ["check", "venues"])
    assert result.exit_code == 0
    assert result.stdout == ""


def test_check_venues_exits_one_and_lists_unmapped_venue(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from bblmlp.storage import connect, init_schema, upsert_games

    warehouse = tmp_path / "w.duckdb"
    con = connect(warehouse)
    init_schema(con)
    upsert_games(con, [_game_row("Some New Stadium")])
    con.close()

    fake_settings = SimpleNamespace(data=SimpleNamespace(warehouse_path=warehouse))
    monkeypatch.setattr("bblmlp.config.load_settings", lambda *a, **k: fake_settings)

    result = runner.invoke(app, ["check", "venues"])
    assert result.exit_code == 1
    assert "Some New Stadium" in result.stdout


def test_build_group_has_features_command():
    result = runner.invoke(app, ["build", "--help"])
    assert result.exit_code == 0
    assert "features" in result.stdout


def test_build_features_writes_team_and_pitcher_rows(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from bblmlp.storage import connect, init_schema, replace_partition

    warehouse = tmp_path / "w.duckdb"
    con = connect(warehouse)
    init_schema(con)

    con.execute("INSERT INTO games (game_pk, season, game_date, game_datetime, home_team, away_team) VALUES "
                "(1, 2024, '2024-03-15', '2024-03-15T18:00', 'NYY', 'BOS'), "
                "(2, 2024, '2024-03-16', '2024-03-16T18:00', 'NYY', 'BOS')")

    import pandas as pd
    replace_partition(con, "team_game_stats", pd.DataFrame({
        "game_pk": [1, 2], "season": [2024, 2024], "team": ["NYY", "NYY"],
        "pa": [36, 41], "xwoba": [0.30, 0.25], "k_pct": [0.25, 0.17], "bb_pct": [0.05, 0.02],
    }), "season")
    replace_partition(con, "pitcher_game_stats", pd.DataFrame({
        "game_pk": [1, 2], "season": [2024, 2024], "pitcher": [500, 500],
        "pitches": [90, 95], "batters_faced": [24, 26], "avg_velo": [94.0, 93.5],
        "xwoba_against": [0.28, 0.30], "k": [6, 7], "bb": [2, 1], "whiffs": [10, 12],
        "swstr_pct": [0.11, 0.13], "is_starter": [True, True],
    }), "season")
    con.close()

    fake_settings = SimpleNamespace(data=SimpleNamespace(warehouse_path=warehouse))
    monkeypatch.setattr("bblmlp.config.load_settings", lambda *a, **k: fake_settings)

    result = runner.invoke(app, ["build", "features", "--season", "2024"])
    assert result.exit_code == 0

    con = connect(warehouse)
    assert con.execute("SELECT COUNT(*) FROM team_features").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM pitcher_features").fetchone()[0] == 2
    con.close()


def test_build_features_spans_season_boundary_but_writes_only_target_season(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from bblmlp.storage import connect, init_schema, replace_partition

    warehouse = tmp_path / "w.duckdb"
    con = connect(warehouse)
    init_schema(con)

    # Three 2023 games (prior-season history) plus one early 2024 game, all for the same team.
    con.execute("INSERT INTO games (game_pk, season, game_date, game_datetime, home_team, away_team) VALUES "
                "(1, 2023, '2023-09-01', '2023-09-01T18:00', 'NYY', 'BOS'), "
                "(2, 2023, '2023-09-02', '2023-09-02T18:00', 'NYY', 'BOS'), "
                "(3, 2023, '2023-09-03', '2023-09-03T18:00', 'NYY', 'BOS'), "
                "(4, 2024, '2024-03-15', '2024-03-15T18:00', 'NYY', 'BOS')")

    import pandas as pd
    replace_partition(con, "team_game_stats", pd.DataFrame({
        "game_pk": [1, 2, 3, 4], "season": [2023, 2023, 2023, 2024], "team": ["NYY"] * 4,
        "pa": [36, 41, 38, 40], "xwoba": [0.30, 0.25, 0.28, 0.27],
        "k_pct": [0.25, 0.17, 0.20, 0.19], "bb_pct": [0.05, 0.02, 0.03, 0.04],
    }), "season")
    con.close()

    fake_settings = SimpleNamespace(data=SimpleNamespace(warehouse_path=warehouse))
    monkeypatch.setattr("bblmlp.config.load_settings", lambda *a, **k: fake_settings)

    result = runner.invoke(app, ["build", "features", "--season", "2024"])
    assert result.exit_code == 0

    con = connect(warehouse)
    row = con.execute(
        "SELECT n_games_30 FROM team_features WHERE game_pk = 4 AND team = 'NYY'"
    ).fetchone()
    assert row is not None
    # The 2024 game's 30-game window must include the three prior 2023 games -- proof that
    # trailing history genuinely spans the season boundary, not zero as the season-scoped bug
    # would produce.
    assert row[0] == 3

    season_2023_rows = con.execute(
        "SELECT COUNT(*) FROM team_features WHERE season = 2023"
    ).fetchone()[0]
    assert season_2023_rows == 0
    con.close()


def test_ingest_kalshi_command_exists():
    result = runner.invoke(app, ["ingest", "kalshi", "--help"])
    assert result.exit_code == 0
