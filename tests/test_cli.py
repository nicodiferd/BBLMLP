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
