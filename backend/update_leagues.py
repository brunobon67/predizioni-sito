import requests
from app import Match, SessionLocal

# ⚠️ METTI QUI LA STESSA API KEY CHE HAI GIÀ USATO
API_KEY = "deebeb24e4fe4b1fbe53c5634108c440"

BASE_URL = "https://api.football-data.org/v4/competitions/{code}/matches"
HEADERS = {"X-Auth-Token": API_KEY}

# Leghe che vogliamo importare
LEAGUES = [
    {"code": "SA", "name": "Serie A"},
    {"code": "PL", "name": "Premier League"},
    {"code": "PD", "name": "La Liga"},
]

# Stagioni: 2024-2025 e 2025-2026
SEASONS = [2024, 2025]


def convert_status(api_status: str) -> str:
    """
    Converte lo status di Football-Data in uno dei nostri:
    - FINISHED
    - UPCOMING
    """
    if api_status == "FINISHED":
        return "FINISHED"
    # Tutto il resto lo trattiamo come partita non ancora finita
    return "UPCOMING"


def fetch_matches(league_code: str, season: int):
    print(f"🔄 Recupero partite per {league_code}, stagione {season}...")
    url = BASE_URL.format(code=league_code)
    params = {"season": season}

    response = requests.get(url, headers=HEADERS, params=params)

    if response.status_code != 200:
        print(
            f"❌ Errore API per {league_code} {season}:",
            response.status_code,
            response.text,
        )
        return None

    data = response.json()
    return data.get("matches", [])


def import_matches(matches, competition_name: str, season: int):
    session = SessionLocal()

    inserted = 0
    updated = 0

    for m in matches:
        match_id = m["id"]
        status = convert_status(m["status"])

        home_goals = None
        away_goals = None

        if status == "FINISHED":
            full_time = m["score"].get("fullTime", {})
            home_goals = full_time.get("home")
            away_goals = full_time.get("away")

        db_match = session.query(Match).filter(Match.id == match_id).first()

        if db_match is None:
            # Nuova partita
            new_match = Match(
                id=match_id,
                competition=competition_name,
                home_team=m["homeTeam"]["name"],
                away_team=m["awayTeam"]["name"],
                date=m["utcDate"],
                status=status,
                home_goals=home_goals,
                away_goals=away_goals,
                season=season,
            )
            session.add(new_match)
            inserted += 1
        else:
            # Aggiorna eventualmente (es. risultato appena finito)
            db_match.competition = competition_name
            db_match.date = m["utcDate"]
            db_match.status = status
            db_match.home_goals = home_goals
            db_match.away_goals = away_goals
            db_match.season = season
            updated += 1

    session.commit()
    session.close()

    print(
        f"✅ {competition_name} {season} → Inseriti: {inserted} | Aggiornati: {updated}"
    )


def main():
    for league in LEAGUES:
        code = league["code"]
        name = league["name"]

        for season in SEASONS:
            matches = fetch_matches(code, season)
            if not matches:
                print(f"⚠️ Nessuna partita per {name} {season}")
                continue

            import_matches(matches, name, season)

    print("🏁 Import completato per tutte le leghe e stagioni richieste.")


if __name__ == "__main__":
    main()
