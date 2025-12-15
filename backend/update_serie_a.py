import os
import requests
from app import Match, SessionLocal

API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing FOOTBALL_DATA_API_KEY env var")

BASE_URL = "https://api.football-data.org/v4/competitions/SA/matches"
HEADERS = {"X-Auth-Token": API_KEY}


def fetch_matches(season):
    print(f"🔄 Recupero partite Serie A stagione {season}...")
    url = f"{BASE_URL}?season={season}"

    response = requests.get(url, headers=HEADERS, timeout=30)

    if response.status_code != 200:
        print("❌ Errore API:", response.status_code, response.text)
        return None

    data = response.json()
    return data.get("matches", [])



def convert_status(api_status):
    if api_status == "FINISHED":
        return "FINISHED"
    return "UPCOMING"


def import_matches(matches, season):
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
            new_match = Match(
                id=match_id,
                competition="Serie A",
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
            db_match.date = m["utcDate"]
            db_match.status = status
            db_match.home_goals = home_goals
            db_match.away_goals = away_goals
            db_match.season = season
            updated += 1

    session.commit()
    session.close()

    print(f"✅ Stagione {season} → Inseriti: {inserted} | Aggiornati: {updated}")



def main():
    seasons = [2024, 2025]  # Stagione 2024-25 e 2025-26

    for season in seasons:
        matches = fetch_matches(season)
        if matches is None:
            print(f"❌ Nessun dato per la stagione {season}")
            continue

        import_matches(matches, season)

    print("🏁 DB aggiornato con tutte le stagioni richieste.")


if __name__ == "__main__":
    main()
