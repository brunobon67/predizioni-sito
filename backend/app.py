import os
import sys
import subprocess
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS

from sqlalchemy import create_engine, Column, Integer, String, or_
from sqlalchemy import BigInteger
from sqlalchemy.orm import sessionmaker, declarative_base


app = Flask(__name__)

CORS(app, resources={
    r"/api/*": {
        "origins": [
            "https://predizioni-sito.netlify.app",
            "http://localhost:5500",
            "http://127.0.0.1:5500"
        ]
    }
})

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///calcio.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# =============================
# Models
# =============================
class Match(Base):
    __tablename__ = "matches"

    id = Column(BigInteger, primary_key=True, index=True)

    external_source = Column(String, nullable=False, default="football-data")
    external_id = Column(BigInteger, nullable=False)

    competition = Column(String, nullable=False)
    home_team = Column(String, nullable=False)
    away_team = Column(String, nullable=False)

    utc_date = Column(String, nullable=False)
    date = Column(String, nullable=False)

    status = Column(String, nullable=False)
    home_goals = Column(Integer, nullable=True)
    away_goals = Column(Integer, nullable=True)
    season = Column(Integer, nullable=True)


class MatchContext(Base):
    __tablename__ = "match_context"

    match_id = Column(BigInteger, primary_key=True, index=True)

    competition = Column(String, nullable=False)
    season = Column(Integer, nullable=False)
    date = Column(String, nullable=False)

    home_team = Column(String, nullable=False)
    away_team = Column(String, nullable=False)

    home_rank_before = Column(Integer, nullable=False)
    away_rank_before = Column(Integer, nullable=False)

    total_teams = Column(Integer, nullable=False)


Base.metadata.create_all(bind=engine)


def db_info():
    session = SessionLocal()
    try:
        count = session.query(Match).count()
        print(f"✅ Database inizializzato, partite presenti: {count}")
    finally:
        session.close()


db_info()


# =============================
# Admin helpers
# =============================
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")


def require_admin():
    req_token = request.headers.get("X-Admin-Token", "")
    if not ADMIN_TOKEN:
        return False, (jsonify({"error": "missing ADMIN_TOKEN env var"}), 500)
    if req_token != ADMIN_TOKEN:
        return False, (jsonify({"error": "unauthorized"}), 401)
    return True, None


@app.route("/api/admin/ping", methods=["GET"])
def admin_ping():
    return jsonify({"admin_token_set": bool(os.getenv("ADMIN_TOKEN"))}), 200


@app.route("/api/admin/import", methods=["POST"])
def admin_import():
    ok, resp = require_admin()
    if not ok:
        return resp

    try:
        script_path = Path(__file__).resolve().parent / "update_leagues.py"

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            check=True
        )

        return jsonify({
            "ok": True,
            "stdout": (result.stdout or "")[-4000:],
            "stderr": (result.stderr or "")[-4000:]
        }), 200

    except subprocess.CalledProcessError as e:
        return jsonify({
            "ok": False,
            "stdout": (e.stdout or "")[-4000:],
            "stderr": (e.stderr or "")[-4000:]
        }), 500


@app.route("/api/admin/update-matches", methods=["POST"])
def admin_update_matches():
    # alias dell'import sincrono
    return admin_import()


from sqlalchemy import text

@app.route("/api/admin/db/check", methods=["GET"])
def admin_db_check():
    ok, resp = require_admin()
    if not ok:
        return resp

    session = SessionLocal()
    try:
        total = session.query(Match).count()
        with_external = session.query(Match).filter(Match.external_id.isnot(None)).count()
        finished_with_score = (
            session.query(Match)
            .filter(Match.status == "FINISHED")
            .filter(Match.home_goals.isnot(None))
            .filter(Match.away_goals.isnot(None))
            .count()
        )

        dup_rows = session.execute(text("""
            SELECT external_source, external_id, COUNT(*) AS c
            FROM matches
            GROUP BY external_source, external_id
            HAVING COUNT(*) > 1
            ORDER BY c DESC
            LIMIT 10
        """)).fetchall()

        # E soprattutto: capire se id interno è diverso da external_id
        sample = session.execute(text("""
            SELECT id, external_id, external_source, competition, date, status
            FROM matches
            ORDER BY id DESC
            LIMIT 5
        """)).fetchall()

        return jsonify({
            "total": total,
            "with_external_id": with_external,
            "finished_with_score": finished_with_score,
            "duplicate_external_top10": [
                {"external_source": r[0], "external_id": r[1], "count": r[2]} for r in dup_rows
            ],
            "sample_last5": [
                {
                    "id": s[0],
                    "external_id": s[1],
                    "external_source": s[2],
                    "competition": s[3],
                    "date": s[4],
                    "status": s[5],
                } for s in sample
            ]
        }), 200
    finally:
        session.close()


# =============================
# API: Teams
# =============================
@app.route("/api/teams", methods=["GET"])
def get_teams():
    competition = request.args.get("competition")
    season = request.args.get("season", type=int)

    session = SessionLocal()
    try:
        q = session.query(Match)
        if competition:
            q = q.filter(Match.competition == competition)
        if season is not None:
            q = q.filter(Match.season == season)

        matches = q.all()

        teams_set = set()
        for m in matches:
            teams_set.add(m.home_team)
            teams_set.add(m.away_team)

        return jsonify({"teams": sorted(list(teams_set))})
    finally:
        session.close()


# =============================
# API: Matches
# =============================
@app.route("/api/matches", methods=["GET"])
def get_matches():
    session = SessionLocal()
    try:
        matches = (
            session.query(Match)
            .filter(Match.status != "FINISHED")
            .order_by(Match.date.asc())
            .all()
        )

        results = [
            {
                "id": m.id,
                "competition": m.competition,
                "home_team": m.home_team,
                "away_team": m.away_team,
                "date": m.date,
                "status": m.status,
                "home_goals": m.home_goals,
                "away_goals": m.away_goals,
                "season": m.season,
                "external_id": m.external_id,
                "external_source": m.external_source,
                "utc_date": m.utc_date,
            }
            for m in matches
        ]
        return jsonify({"matches": results})
    finally:
        session.close()


# =============================
# API: Stats  (qui lascio la tua versione estesa: l'hai già nel tuo file)
# =============================
@app.route("/api/stats", methods=["GET"])
def get_stats():
    team = request.args.get("team")
    competition = request.args.get("competition")
    season_param = request.args.get("season", type=int)

    if not team:
        return jsonify({"error": "Parametro 'team' obbligatorio"}), 400

    session = SessionLocal()
    try:
        q = session.query(Match).filter(Match.status == "FINISHED")

        if competition:
            q = q.filter(Match.competition == competition)
        if season_param is not None:
            q = q.filter(Match.season == season_param)

        q = q.filter(or_(Match.home_team == team, Match.away_team == team))
        matches = q.order_by(Match.date.asc()).all()

        # (Per brevità: mantieni qui il tuo blocco stats attuale se già funzionante)
        # Io qui restituisco almeno il minimo, così non rompi nulla.
        matches_played = len(matches)
        wins = draws = losses = 0
        goals_scored = goals_conceded = 0

        for m in matches:
            hg = m.home_goals or 0
            ag = m.away_goals or 0
            if m.home_team == team:
                gf, ga = hg, ag
            else:
                gf, ga = ag, hg

            goals_scored += gf
            goals_conceded += ga
            if gf > ga:
                wins += 1
            elif gf == ga:
                draws += 1
            else:
                losses += 1

        return jsonify({
            "team": team,
            "competition": competition if competition else "All",
            "season": season_param if season_param is not None else "All",
            "matches_played": matches_played,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "goals_scored": goals_scored,
            "goals_conceded": goals_conceded,
        })
    finally:
        session.close()


@app.route("/api/standings", methods=["GET"])
def get_standings():
    competition = request.args.get("competition")
    season = request.args.get("season", type=int)
    date_limit = request.args.get("date")

    if not competition or season is None or not date_limit:
        return jsonify({"error": "competition, season and date are required"}), 400

    session = SessionLocal()
    try:
        q = (
            session.query(Match)
            .filter(Match.status == "FINISHED")
            .filter(Match.competition == competition)
            .filter(Match.season == season)
            .filter(Match.date <= date_limit)
        )

        matches = q.all()

        table = {}

        def ensure(team_name: str):
            if team_name not in table:
                table[team_name] = {
                    "team": team_name,
                    "points": 0,
                    "played": 0,
                    "wins": 0,
                    "draws": 0,
                    "losses": 0,
                    "gf": 0,
                    "ga": 0,
                }

        for m in matches:
            home, away = m.home_team, m.away_team
            hg, ag = m.home_goals or 0, m.away_goals or 0

            ensure(home)
            ensure(away)

            table[home]["played"] += 1
            table[away]["played"] += 1

            table[home]["gf"] += hg
            table[home]["ga"] += ag
            table[away]["gf"] += ag
            table[away]["ga"] += hg

            if hg > ag:
                table[home]["wins"] += 1
                table[home]["points"] += 3
                table[away]["losses"] += 1
            elif hg < ag:
                table[away]["wins"] += 1
                table[away]["points"] += 3
                table[home]["losses"] += 1
            else:
                table[home]["draws"] += 1
                table[away]["draws"] += 1
                table[home]["points"] += 1
                table[away]["points"] += 1

        rows = list(table.values())
        for r in rows:
            r["gd"] = r["gf"] - r["ga"]

        rows.sort(key=lambda r: (r["points"], r["gd"], r["gf"], r["played"], r["team"]), reverse=True)
        for i, r in enumerate(rows, start=1):
            r["rank"] = i

        return jsonify({"competition": competition, "season": season, "date": date_limit, "standings": rows})
    finally:
        session.close()


@app.route("/api/predict", methods=["POST"])
def predict_match():
    data = request.get_json(force=True)
    match_id = data.get("match_id")
    model = data.get("model")

    if not match_id or not model:
        return jsonify({"error": "match_id e model sono obbligatori"}), 400

    session = SessionLocal()
    try:
        match = session.query(Match).filter(Match.id == match_id).first()
        if not match:
            return jsonify({"error": "Match non trovato"}), 404

        return jsonify({
            "match_id": match_id,
            "model": model,
            "probabilities": {
                "home_win": 0.40,
                "draw": 0.30,
                "away_win": 0.30,
                "explanation": f"Modello: {model}. Placeholder."
            }
        })
    finally:
        session.close()


if __name__ == "__main__":
    app.run(debug=True)
