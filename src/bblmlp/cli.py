"""BBLMLP command-line interface."""
import typer

app = typer.Typer(help="Baseball ML prediction for Kalshi single-game markets.")
ingest_app = typer.Typer(help="Ingest data into the warehouse.")
app.add_typer(ingest_app, name="ingest")


@app.command()
def version() -> None:
    """Print the installed version."""
    from bblmlp import __version__

    typer.echo(__version__)


@app.command("init-db")
def init_db() -> None:
    """Create the DuckDB warehouse and its tables."""
    from bblmlp.config import load_settings
    from bblmlp.storage import connect, init_schema

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    con.close()
    typer.echo(f"Initialized warehouse at {settings.data.warehouse_path}")


@ingest_app.command("mlb")
def ingest_mlb(
    live: bool = typer.Option(False, "--live", help="Ingest today's schedule."),
    date: str = typer.Option(None, "--date", help="Ingest a single date (YYYY-MM-DD)."),
    backfill: bool = typer.Option(
        False, "--backfill", help="Backfill all seasons in settings."
    ),
) -> None:
    """Ingest MLB games into the warehouse."""
    import datetime as _dt

    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.ingest import ingest_range, ingest_seasons
    from bblmlp.ingest.mlb.statsapi_client import fetch_schedule
    from bblmlp.storage import connect, init_schema

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)

    if backfill:
        written = ingest_seasons(con, fetch_schedule, settings.data.backfill_seasons)
        con.close()
        typer.echo(f"Backfilled {written} games across {settings.data.backfill_seasons}")
        return

    target = date or (_dt.date.today().isoformat() if live else None)
    if target is None:
        con.close()
        raise typer.BadParameter("Provide --live, --date YYYY-MM-DD, or --backfill")

    season = int(target[:4])
    written = ingest_range(con, fetch_schedule, target, target, season)
    con.close()
    typer.echo(f"Ingested {written} games for {target}")


@ingest_app.command("statcast")
def ingest_statcast(season: int = typer.Option(..., "--season")) -> None:
    """Backfill a season of Statcast pitch data."""
    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.statcast import (
        fetch_statcast_season,
        normalize_statcast,
        write_statcast,
    )
    from bblmlp.storage import connect, init_schema

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    raw = fetch_statcast_season(season)
    out = normalize_statcast(raw, season=season)
    n = write_statcast(con, out)
    con.close()
    typer.echo(f"Wrote {n} statcast rows for {season}")


@ingest_app.command("players")
def ingest_players() -> None:
    """Refresh the Chadwick player-id crosswalk."""
    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.players import fetch_chadwick, normalize_players
    from bblmlp.storage import connect, init_schema, replace_all

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    n = replace_all(con, "player_ids", normalize_players(fetch_chadwick()))
    con.close()
    typer.echo(f"Loaded {n} players")


if __name__ == "__main__":
    app()
