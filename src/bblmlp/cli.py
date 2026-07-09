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
) -> None:
    """Ingest MLB games into the warehouse."""
    import datetime as _dt

    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.ingest import ingest_range
    from bblmlp.ingest.mlb.statsapi_client import fetch_schedule
    from bblmlp.storage import connect, init_schema

    target = date or (_dt.date.today().isoformat() if live else None)
    if target is None:
        raise typer.BadParameter("Provide --live or --date YYYY-MM-DD")

    season = int(target[:4])
    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    written = ingest_range(con, fetch_schedule, target, target, season)
    con.close()
    typer.echo(f"Ingested {written} games for {target}")


if __name__ == "__main__":
    app()
