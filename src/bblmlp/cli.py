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


@ingest_app.command("fangraphs")
def ingest_fangraphs(season: int = typer.Option(..., "--season")) -> None:
    """Backfill a season of FanGraphs season tables (team and player)."""
    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.fangraphs import (
        fetch_batting_stats,
        fetch_pitching_stats,
        fetch_team_batting,
        fetch_team_pitching,
        normalize_batter_stats,
        normalize_pitcher_stats,
        normalize_team_batting,
        normalize_team_pitching,
    )
    from bblmlp.storage import connect, ensure_table_from_df, init_schema, replace_partition

    # (table_name, fetch_fn, normalize_fn)
    specs = [
        ("team_batting_season", fetch_team_batting, normalize_team_batting),
        ("team_pitching_season", fetch_team_pitching, normalize_team_pitching),
        ("pitcher_stats_season", fetch_pitching_stats, normalize_pitcher_stats),
        ("batter_stats_season", fetch_batting_stats, normalize_batter_stats),
    ]

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    for table, fetch, normalize in specs:
        df = normalize(fetch(season), season=season)
        ensure_table_from_df(con, table, df)
        n = replace_partition(con, table, df, "season")
        typer.echo(f"Wrote {n} rows to {table} for {season}")
    con.close()


@ingest_app.command("standings")
def ingest_standings(season: int = typer.Option(..., "--season")) -> None:
    """Ingest a season of standings into the warehouse."""
    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.standings import fetch_standings, normalize_standings
    from bblmlp.storage import connect, init_schema, replace_partition

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    df = normalize_standings(fetch_standings(season), season=season)
    n = replace_partition(con, "standings", df, "season")
    con.close()
    typer.echo(f"Wrote {n} standings rows for {season}")


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
