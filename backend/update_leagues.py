import os
import requests
from app.models import Match
from app.db import SessionLocal

API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing FOOTBALL_DATA_API_KEY env var")

BASE_URL = "https://api.football-data.org/v4/competitions/{code}/matches"
HEADERS = {"X-Auth-Token": API_KEY}

EXTERNAL_SOURCE = "football-data"

# Leghe che vogliamo importare
LEAGUES = [
    {"code": "SA", "name": "Serie A"},
    {"code": "PL", "name": "Premier League"},
    {"code": "PD", "name": "La Liga"},
    {"code": "SB", "name": "Serie B"},
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
    return "UPCOMING"


def fetch_matches(league_code: str, season: int):
    print(f"ðŸ”„ Recupero partite per {league_code}, stagione {season}...")
    url = BASE_URL.format(code=league_code)
    params = {"season": season}

    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=30)
    except requests.RequestException as e:
        print(f"âŒ Errore di rete per {league_code} {season}: {e}")
        return None

    if response.status_code != 200:
        print(
            f"âŒ Errore API per {league_code} {season}:",
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
        match_external_id = m.get("id")
        if match_external_id is None:
            # match senza id -> ignoriamo
            continue

        status = convert_status(m.get("status", ""))

        # Date
        utc_date = m.get("utcDate") or ""
        date_only = utc_date[:10] if len(utc_date) >= 10 else ""  # YYYY-MM-DD

        # Teams
        home_team = (m.get("homeTeam") or {}).get("name") or ""
        away_team = (m.get("awayTeam") or {}).get("name") or ""

        # Goals (solo se FINISHED)
        home_goals = None
        away_goals = None
        if status == "FINISHED":
            ft = ((m.get("score") or {}).get("fullTime")) or {}
            home_goals = ft.get("home")
            away_goals = ft.get("away")

        # Cerca per (external_source, external_id) â€” non per PK interna!
        db_match = (
            session.query(Match)
            .filter(Match.external_source == EXTERNAL_SOURCE)
            .filter(Match.external_id == match_external_id)
            .first()
        )

        if db_match is None:
            # Nuova partita
            new_match = Match(
                external_source=EXTERNAL_SOURCE,
                external_id=match_external_id,
                competition=competition_name,
                home_team=home_team,
                away_team=away_team,
                utc_date=utc_date,
                date=date_only,
                status=status,
                home_goals=home_goals,
                away_goals=away_goals,
                season=season,
            )
            session.add(new_match)
            inserted += 1
        else:
            # Aggiorna dati base
            db_match.competition = competition_name
            db_match.home_team = home_team
            db_match.away_team = away_team
            db_match.utc_date = utc_date
            db_match.date = date_only
            db_match.status = status
            db_match.season = season

            # NON sovrascrivere gol se non FINISHED (evita di cancellare score)
            if status == "FINISHED":
                db_match.home_goals = home_goals
                db_match.away_goals = away_goals

            updated += 1

    session.commit()
    session.close()

    print(f"âœ… {competition_name} {season} â†’ Inseriti: {inserted} | Aggiornati: {updated}")


def main():
    for league in LEAGUES:
        code = league["code"]
        name = league["name"]

        for season in SEASONS:
            matches = fetch_matches(code, season)
            if not matches:
                print(f"âš ï¸ Nessuna partita per {name} {season}")
                continue

            import_matches(matches, name, season)

    print("ðŸ Import completato per tutte le leghe e stagioni richieste.")


if __name__ == "__main__":
    main()
