# backend/app/routes/public.py

from flask import Blueprint, request, jsonify
from sqlalchemy import or_

from app.db import SessionLocal
from app.models import Match, MatchContext

bp_public = Blueprint("public", __name__)


@bp_public.route("/api/teams", methods=["GET"])
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


@bp_public.route("/api/matches", methods=["GET"])
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


@bp_public.route("/api/stats", methods=["GET"])
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

        # Se MatchContext non è popolato o non passi competition+season,
        # ritorna comunque le stats base come faceva il tuo vecchio codice.
        # (La parte "vs_top/mid/bottom" dipende dal context). :contentReference[oaicite:5]{index=5}

        played = 0
        wins = 0
        draws = 0
        losses = 0
        gf = 0
        ga = 0

        for m in matches:
            played += 1
            hg = m.home_goals or 0
            ag = m.away_goals or 0

            if m.home_team == team:
                gf += hg
                ga += ag
                if hg > ag:
                    wins += 1
                elif hg < ag:
                    losses += 1
                else:
                    draws += 1
            else:
                gf += ag
                ga += hg
                if ag > hg:
                    wins += 1
                elif ag < hg:
                    losses += 1
                else:
                    draws += 1

        points = wins * 3 + draws
        ppg = points / played if played else 0.0

        return jsonify({
            "team": team,
            "competition": competition,
            "season": season_param,
            "overall": {
                "played": played,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "gf": gf,
                "ga": ga,
                "points": points,
                "ppg": ppg
            }
        })
    finally:
        session.close()


@bp_public.route("/api/standings", methods=["GET"])
def get_standings():
    competition = request.args.get("competition")
    season = request.args.get("season", type=int)
    date_limit = request.args.get("date")  # opzionale

    if not competition or season is None:
        return jsonify({"error": "competition e season obbligatori"}), 400

    session = SessionLocal()
    try:
        q = (
            session.query(Match)
            .filter(Match.status == "FINISHED")
            .filter(Match.competition == competition)
            .filter(Match.season == int(season))
        )

        if date_limit:
            q = q.filter(Match.date <= date_limit)

        matches = q.order_by(Match.date.asc(), Match.id.asc()).all()

        teams = set()
        for m in matches:
            teams.add(m.home_team)
            teams.add(m.away_team)

        table = {}
        for t in teams:
            table[t] = {"team": t, "played": 0, "wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0, "points": 0}

        for m in matches:
            home = m.home_team
            away = m.away_team
            hg = m.home_goals or 0
            ag = m.away_goals or 0

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
