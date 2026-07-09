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
