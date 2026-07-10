"""Quick read-only tour of the DuckDB warehouse — run to eyeball the data.

    PYTHONPATH=src .venv/bin/python scripts/peek.py
    # or, once the console script imports cleanly:
    uv run --no-sync python scripts/peek.py
"""
from __future__ import annotations

import duckdb

DB = "data/warehouse.duckdb"


def main() -> None:
    con = duckdb.connect(DB, read_only=True)
    tables = sorted(r[0] for r in con.execute(
        "select table_name from information_schema.tables where table_schema='main'"
    ).fetchall())

    print(f"\n=== warehouse: {DB} ===")
    print(f"{'table':24} {'rows':>12} {'cols':>6}")
    print("-" * 44)
    for t in tables:
        n = con.execute(f"select count(*) from {t}").fetchone()[0]
        c = len(con.execute(f"PRAGMA table_info({t})").fetchall())
        print(f"{t:24} {n:>12,} {c:>6}")

    def show(title: str, sql: str) -> None:
        print(f"\n--- {title} ---")
        try:
            print(con.execute(sql).fetchdf().to_string(index=False))
        except Exception as e:  # a table might be empty/absent
            print(f"(skipped: {e})")

    show("games by month (2024)",
         "select strftime(game_date,'%Y-%m') m, count(*) games, "
         "sum(home_win) home_wins from games where home_win is not null "
         "group by m order by m")
    show("home-field win rate",
         "select round(avg(home_win),3) home_win_rate, count(*) decided_games "
         "from games where home_win is not null")
    show("top 5 pitchers by strikeouts (pitcher_game_stats -> season total)",
         "select p.pitcher, sum(p.k) K, sum(p.pitches) pitches, "
         "round(avg(p.avg_velo),1) velo from pitcher_game_stats p "
         "group by p.pitcher order by K desc limit 5")
    show("hardest-throwing starters (min 1000 pitches)",
         "select pitcher, round(avg(avg_velo),1) velo, sum(pitches) pitches "
         "from pitcher_game_stats where is_starter group by pitcher "
         "having sum(pitches) > 1000 order by velo desc limit 5")
    show("statcast: pitch-type mix",
         "select pitch_type, count(*) n, round(avg(release_speed),1) mph "
         "from statcast_pitches where pitch_type is not null "
         "group by pitch_type order by n desc limit 8")
    show("team offense (team_batting_season: wRC+)",
         "select team, wrc_plus, woba from team_batting_season "
         "order by wrc_plus desc limit 5")

    print("\n=== explore interactively ===")
    print("  • DuckDB web UI (browser):")
    print("      .venv/bin/python -c \"import duckdb; "
          "duckdb.connect('data/warehouse.duckdb').execute("
          "'INSTALL ui; LOAD ui; CALL start_ui()'); input('UI running — Enter to quit')\"")
    print("  • one-off SQL:")
    print("      .venv/bin/python -c \"import duckdb; "
          "print(duckdb.connect('data/warehouse.duckdb',read_only=True)"
          ".sql('SELECT * FROM games LIMIT 5'))\"")
    print("  • or open data/warehouse.duckdb in Cursor's DuckDB viewer / DBeaver / TablePlus\n")
    con.close()


if __name__ == "__main__":
    main()
