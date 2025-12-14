from datetime import datetime
from app import SessionLocal, Match, MatchContext


def compute_context_for_competition_season(session, competition, season):
    # prendiamo tutte le partite finite
    matches_raw = (
        session.query(Match)
        .filter(Match.status == "FINISHED")
        .filter(Match.competition == competition)
        .filter(Match.season == season)
        .all()
    )

    if not matches_raw:
        print(f"⚠️ Nessuna partita FINISHED per {competition} {season}")
        return 0

    # ORDINE CRONOLOGICO CORRETTO (DATE come datetime)
    matches = sorted(
        matches_raw,
        key=lambda m: (datetime.fromisoformat(m.date), m.id)
    )

    # set squadre
    teams = set()
    for m in matches:
        teams.add(m.home_team)
        teams.add(m.away_team)

    teams = sorted(list(teams))
    total_teams = len(teams)

    # classifica progressiva
    table = {
        t: {"points": 0, "gf": 0, "ga": 0, "played": 0}
        for t in teams
    }

    def ranking_snapshot():
        rows = []
        for t, s in table.items():
            gd = s["gf"] - s["ga"]
            rows.append((t, s["points"], gd, s["gf"], s["played"]))

        rows.sort(
            key=lambda x: (x[1], x[2], x[3], x[4], x[0]),
            reverse=True
        )

        rank = {}
        for i, r in enumerate(rows, start=1):
            rank[r[0]] = i
        return rank

    inserted = 0

    for m in matches:
        # rank PRIMA della partita
        ranks = ranking_snapshot()

        home_rank_before = ranks.get(m.home_team, total_teams)
        away_rank_before = ranks.get(m.away_team, total_teams)

        # UPSERT
        ctx = (
            session.query(MatchContext)
            .filter(MatchContext.match_id == m.id)
            .first()
        )
        if not ctx:
            ctx = MatchContext(match_id=m.id)
            session.add(ctx)

        ctx.competition = competition
        ctx.season = season
        ctx.date = m.date
        ctx.home_team = m.home_team
        ctx.away_team = m.away_team
        ctx.home_rank_before = home_rank_before
        ctx.away_rank_before = away_rank_before
        ctx.total_teams = total_teams

        inserted += 1

        # aggiorna classifica DOPO la partita
        hg = m.home_goals or 0
        ag = m.away_goals or 0

        table[m.home_team]["played"] += 1
        table[m.away_team]["played"] += 1

        table[m.home_team]["gf"] += hg
        table[m.home_team]["ga"] += ag
        table[m.away_team]["gf"] += ag
        table[m.away_team]["ga"] += hg

        if hg > ag:
            table[m.home_team]["points"] += 3
        elif hg < ag:
            table[m.away_team]["points"] += 3
        else:
            table[m.home_team]["points"] += 1
            table[m.away_team]["points"] += 1

    return inserted


def main():
    session = SessionLocal()
    try:
        combos = (
            session.query(Match.competition, Match.season)
            .filter(Match.status == "FINISHED")
            .distinct()
            .all()
        )

        total = 0
        for comp, season in combos:
            n = compute_context_for_competition_season(session, comp, season)
            session.commit()
            print(f"✅ Context calcolato per {comp} {season}: {n} righe")
            total += n

        print(f"🎯 Totale righe context scritte: {total}")

    finally:
        session.close()


if __name__ == "__main__":
    main()
