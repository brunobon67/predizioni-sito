import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import Base, Match, MatchContext

SQLITE_URL = "sqlite:///calcio.db"

POSTGRES_URL = os.getenv("DATABASE_URL")
if not POSTGRES_URL:
    raise RuntimeError("DATABASE_URL non impostata")

if POSTGRES_URL.startswith("postgres://"):
    POSTGRES_URL = POSTGRES_URL.replace("postgres://", "postgresql://", 1)

sqlite_engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
pg_engine = create_engine(POSTGRES_URL)

SQLiteSession = sessionmaker(bind=sqlite_engine)
PGSession = sessionmaker(bind=pg_engine)

def main():
    Base.metadata.create_all(bind=pg_engine)

    s_sqlite = SQLiteSession()
    s_pg = PGSession()

    try:
        # Pulisci Postgres (se ripeti la migrazione)
        s_pg.query(MatchContext).delete()
        s_pg.query(Match).delete()
        s_pg.commit()

        matches = s_sqlite.query(Match).all()
        print(f"SQLite matches: {len(matches)}")

        s_pg.bulk_save_objects([
            Match(
                id=m.id,
                competition=m.competition,
                home_team=m.home_team,
                away_team=m.away_team,
                date=m.date,
                status=m.status,
                home_goals=m.home_goals,
                away_goals=m.away_goals,
                season=m.season,
            ) for m in matches
        ])
        s_pg.commit()
        print("✅ Matches migrati")

        ctx = s_sqlite.query(MatchContext).all()
        print(f"SQLite match_context: {len(ctx)}")

        s_pg.bulk_save_objects([
            MatchContext(
                match_id=c.match_id,
                competition=c.competition,
                season=c.season,
                date=c.date,
                home_team=c.home_team,
                away_team=c.away_team,
                home_rank_before=c.home_rank_before,
                away_rank_before=c.away_rank_before,
                total_teams=c.total_teams,
            ) for c in ctx
        ])
        s_pg.commit()
        print("✅ MatchContext migrato")

    finally:
        s_sqlite.close()
        s_pg.close()

if __name__ == "__main__":
    main()
