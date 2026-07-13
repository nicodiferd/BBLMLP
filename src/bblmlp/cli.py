"""BBLMLP command-line interface."""
import typer

app = typer.Typer(help="Baseball ML prediction for Kalshi single-game markets.")
ingest_app = typer.Typer(help="Ingest data into the warehouse.")
build_app = typer.Typer(help="Build derived tables from ingested data.")
check_app = typer.Typer(help="Repeatable data-quality checks against the warehouse.")
app.add_typer(ingest_app, name="ingest")
app.add_typer(build_app, name="build")
app.add_typer(check_app, name="check")


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
    from bblmlp.ingest.mlb.fangraphs import FANGRAPHS_SPECS
    from bblmlp.storage import connect, ensure_table_from_df, init_schema, replace_partition

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    for table, fetch, normalize in FANGRAPHS_SPECS:
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


@ingest_app.command("live")
def ingest_live(
    date: str = typer.Option(None, "--date", help="Date to ingest (YYYY-MM-DD); defaults to today."),
) -> None:
    """Ingest today's live lineups/probables into the warehouse."""
    import datetime as _dt

    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.live import fetch_today_games, normalize_live_lineups
    from bblmlp.storage import connect, init_schema, replace_partition

    target = date or _dt.date.today().isoformat()
    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    df = normalize_live_lineups(fetch_today_games(target), game_date=target)
    n = replace_partition(con, "live_lineups", df, "game_date")
    con.close()
    typer.echo(f"Wrote {n} live lineup rows for {target}")


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


@ingest_app.command("all")
def ingest_all_cmd(
    date: str = typer.Option(
        None, "--date", help="Ingest a single live date (YYYY-MM-DD): players + that day's schedule."
    ),
    backfill: bool = typer.Option(
        False, "--backfill", help="Backfill every source across settings.data.backfill_seasons."
    ),
) -> None:
    """Run the full MLB ingest pipeline: players -> games -> statcast -> fangraphs -> standings."""
    from types import SimpleNamespace

    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.fangraphs import FANGRAPHS_SPECS
    from bblmlp.ingest.mlb.ingest import ingest_all
    from bblmlp.ingest.mlb.players import fetch_chadwick
    from bblmlp.ingest.mlb.standings import fetch_standings
    from bblmlp.ingest.mlb.statcast import fetch_statcast_season
    from bblmlp.ingest.mlb.statsapi_client import fetch_schedule
    from bblmlp.storage import connect, init_schema

    if not date and not backfill:
        raise typer.BadParameter("Provide --date YYYY-MM-DD or --backfill")

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)

    if backfill:
        # Full pipeline across every configured season.
        fetchers = {
            "chadwick": fetch_chadwick,
            "schedule": fetch_schedule,
            "statcast": fetch_statcast_season,
            "fangraphs": FANGRAPHS_SPECS,
            "standings": fetch_standings,
            "team_crosswalk": True,
            "rollups": True,
        }
        run_settings = settings
    else:
        # One live day: players (for id resolution) + that day's schedule only.
        # Season-granular sources (statcast/fangraphs/standings) don't apply to
        # a single date, so they're deliberately left out of `fetchers` — the
        # orchestrator skips any source whose key is absent.
        season = int(date[:4])
        fetchers = {
            "chadwick": fetch_chadwick,
            "schedule": lambda s, e: fetch_schedule(date, date),
        }
        run_settings = SimpleNamespace(data=SimpleNamespace(backfill_seasons=[season]))

    counts = ingest_all(con, run_settings, fetchers=fetchers)
    con.close()
    for source, n in counts.items():
        typer.echo(f"{source}: {n}")


@build_app.command("team-crosswalk")
def build_team_crosswalk_cmd(season: int = typer.Option(..., "--season")) -> None:
    """Reconcile team_id against Statcast/FanGraphs abbreviations for a season."""
    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.team_crosswalk import build_team_crosswalk
    from bblmlp.storage import connect, init_schema, replace_partition, table_names

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    standings = con.execute(
        "SELECT season, team_id, team_name FROM standings WHERE season = ?", [season]
    ).df()
    games = con.execute(
        "SELECT game_pk, season, game_type, home_team_id, away_team_id FROM games WHERE season = ?",
        [season],
    ).df()
    statcast = con.execute(
        "SELECT game_pk, home_team, away_team FROM statcast_pitches WHERE season = ?", [season]
    ).df()
    if "team_batting_season" in table_names(con):
        fangraphs = con.execute(
            "SELECT season, team FROM team_batting_season WHERE season = ?", [season]
        ).df()
    else:
        import pandas as pd

        fangraphs = pd.DataFrame(columns=["season", "team"])
    out = build_team_crosswalk(standings, games, statcast, fangraphs)
    n = replace_partition(con, "team_crosswalk", out, "season")
    con.close()
    typer.echo(f"Wrote {n} team_crosswalk rows for {season}")


@build_app.command("rollups")
def build_rollups(season: int = typer.Option(..., "--season")) -> None:
    """Compute Statcast-derived pitcher/team game rollups for a season."""
    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.rollups import pitcher_game_stats, team_game_stats
    from bblmlp.storage import connect, init_schema, replace_partition

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    pitches = con.execute(
        "SELECT * FROM statcast_pitches WHERE season = ?", [season]
    ).df()
    pitcher_rows = replace_partition(con, "pitcher_game_stats", pitcher_game_stats(pitches), "season")
    team_rows = replace_partition(con, "team_game_stats", team_game_stats(pitches), "season")
    con.close()
    typer.echo(f"Wrote {pitcher_rows} pitcher-game rows and {team_rows} team-game rows for {season}")


@build_app.command("park-reference")
def build_park_reference_cmd() -> None:
    """Build the park_reference table from games.venue (no --season: needs full history)."""
    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.park_reference import build_park_reference
    from bblmlp.storage import connect, init_schema, replace_all

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    games = con.execute("SELECT game_type, venue FROM games").df()
    out = build_park_reference(games)
    n = replace_all(con, "park_reference", out)
    con.close()
    typer.echo(f"Wrote {n} park_reference rows")


@check_app.command("venues")
def check_venues_cmd() -> None:
    """Report any games.venue string not yet mapped in park_reference (sponsor rename/relocation guard)."""
    from bblmlp.config import load_settings
    from bblmlp.ingest.mlb.park_reference import find_unmapped_venues
    from bblmlp.storage import connect, init_schema

    settings = load_settings()
    con = connect(settings.data.warehouse_path)
    init_schema(con)
    games = con.execute("SELECT game_type, venue FROM games").df()
    con.close()
    unmapped = find_unmapped_venues(games)
    if not unmapped:
        raise typer.Exit(code=0)
    for venue in sorted(unmapped):
        typer.echo(venue)
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
