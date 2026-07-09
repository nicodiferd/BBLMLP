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


if __name__ == "__main__":
    app()
