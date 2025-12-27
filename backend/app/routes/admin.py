# backend/app/routes/admin.py

import os
import sys
import subprocess
from pathlib import Path

from flask import Blueprint, request, jsonify
from sqlalchemy import text

from app.db import SessionLocal
from app.models import Match, MatchContext

bp_admin = Blueprint("admin", __name__)



def require_admin():
    expected = (os.getenv("ADMIN_TOKEN", "") or "").strip()
    received = (request.headers.get("X-Admin-Token", "") or "").strip()

    if not expected:
        return False, (jsonify({"error": "missing ADMIN_TOKEN env var"}), 500)
    if received != expected:
        return False, (jsonify({"error": "unauthorized"}), 401)

    return True, None


def _rebuild_context_all_internal(only_finished: bool = True, limit=None):
    """
    Ricostruisce match_context per tutte le coppie (competition, season).
    Usata internamente dopo /api/admin/import per automatizzare top/mid/bottom + ranking.
    (Questa funzione arriva dal tuo vecchio app.py) :contentReference[oaicite:2]{index=2}
    """
    session = SessionLocal()
    try:
        where = "WHERE status='FINISHED'" if only_finished else ""
        lim_sql = "LIMIT :lim" if limit else ""
        params = {"lim": int(limit)} if limit else {}

        pairs = session.execute(text(f"""
            SELECT competition, season
            FROM matches
            {where}
            GROUP BY competition, season
            ORDER BY competition, season
            {lim_sql}
        """), params).fetchall()

        pairs = [(p[0], int(p[1])) for p in pairs if p[0] is not None and p[1] is not None]

        results = []

        for comp, seas in pairs:
            matches = (
                session.query(Match)
                .filter(Match.status == "FINISHED")
                .filter(Match.competition == comp)
                .filter(Match.season == seas)
                .order_by(Match.date.asc(), Match.id.asc())
                .all()
            )

            if not matches:
                results.append({"competition": comp, "season": seas, "inserted": 0, "total_teams": 0})
                continue

            teams = set()
            for m in matches:
                teams.add(m.home_team)
                teams.add(m.away_team)
            teams = sorted(list(teams))
            total_teams = len(teams)

            session.execute(text("""
                DELETE FROM match_context
                WHERE competition = :c AND season = :s
            """), {"c": comp, "s": seas})

            table = {t: {"points": 0, "gf": 0, "ga": 0, "played": 0} for t in teams}

            def rank_map():
                rows = []
                for t, v in table.items():
                    gd = v["gf"] - v["ga"]
                    rows.append((t, v["points"], gd, v["gf"], v["played"]))
                rows.sort(key=lambda r: (r[1], r[2], r[3], r[4], r[0]), reverse=True)
                return {team: idx + 1 for idx, (team, *_rest) in enumerate(rows)}

            inserted = 0

            for m in matches:
                ranks_before = rank_map()
                home_rank_before = ranks_before.get(m.home_team, total_teams)
                away_rank_before = ranks_before.get(m.away_team, total_teams)

                session.add(MatchContext(
                    match_id=m.id,
                    competition=comp,
                    season=seas,
                    date=m.date,
                    home_team=m.home_team,
                    away_team=m.away_team,
                    home_rank_before=home_rank_before,
                    away_rank_before=away_rank_before,
                    total_teams=total_teams
                ))
                inserted += 1

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

            session.commit()

            results.append({
                "competition": comp,
                "season": seas,
                "inserted": inserted,
                "total_teams": total_teams
            })

        return {"ok": True, "pairs": len(results), "results": results}
    finally:
        session.close()


@bp_admin.route("/api/admin/ping", methods=["GET"])
def admin_ping():
    return jsonify({"admin_token_set": bool(os.getenv("ADMIN_TOKEN"))}), 200


@bp_admin.route("/api/admin/import", methods=["POST"])
def admin_import():
    ok, resp = require_admin()
    if not ok:
        return resp

    try:
        script_path = Path(__file__).resolve().parents[2] / "update_leagues.py"
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            check=True
        )

        rebuild_summary = _rebuild_context_all_internal(only_finished=True)

        return jsonify({
            "ok": True,
            "stdout": (result.stdout or "")[-4000:],
            "stderr": (result.stderr or "")[-4000:],
            "context_rebuild": rebuild_summary
        }), 200

    except subprocess.CalledProcessError as e:
        return jsonify({
            "ok": False,
            "stdout": (e.stdout or "")[-4000:],
            "stderr": (e.stderr or "")[-4000:],
        }), 500


@bp_admin.route("/api/admin/update-matches", methods=["POST"])
def admin_update_matches():
    return admin_import()


@bp_admin.route("/api/admin/db/check", methods=["GET"])
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


@bp_admin.route("/api/admin/context/rebuild", methods=["POST"])
def admin_rebuild_context():
    ok, resp = require_admin()
    if not ok:
        return resp

    payload = request.get_json(force=True) or {}
    competition = payload.get("competition")
    season = payload.get("season")

    if not competition or season is None:
        return jsonify({"error": "competition and season are required"}), 400

    season = int(season)

    session = SessionLocal()
    try:
        matches = (
            session.query(Match)
            .filter(Match.status == "FINISHED")
            .filter(Match.competition == competition)
            .filter(Match.season == season)
            .order_by(Match.date.asc(), Match.id.asc())
            .all()
        )

        if not matches:
            return jsonify({"ok": True, "message": "No FINISHED matches found", "inserted": 0, "total_teams": 0}), 200

        teams = set()
        for m in matches:
            teams.add(m.home_team)
            teams.add(m.away_team)
        teams = sorted(list(teams))
        total_teams = len(teams)

        session.execute(text("""
            DELETE FROM match_context
            WHERE competition = :competition AND season = :season
        """), {"competition": competition, "season": season})

        table = {t: {"points": 0, "gf": 0, "ga": 0, "played": 0} for t in teams}

        def rank_map():
            rows = []
            for t, v in table.items():
                gd = v["gf"] - v["ga"]
                rows.append((t, v["points"], gd, v["gf"], v["played"]))
            rows.sort(key=lambda r: (r[1], r[2], r[3], r[4], r[0]), reverse=True)
            return {team: idx + 1 for idx, (team, *_rest) in enumerate(rows)}

        inserted = 0

        for m in matches:
            ranks_before = rank_map()
            home_rank_before = ranks_before.get(m.home_team, total_teams)
            away_rank_before = ranks_before.get(m.away_team, total_teams)

            session.add(MatchContext(
                match_id=m.id,
                competition=competition,
                season=season,
                date=m.date,
                home_team=m.home_team,
                away_team=m.away_team,
                home_rank_before=home_rank_before,
                away_rank_before=away_rank_before,
                total_teams=total_teams
            ))
            inserted += 1

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

        session.commit()

        return jsonify({
            "ok": True,
            "competition": competition,
            "season": season,
            "total_teams": total_teams,
            "inserted": inserted
        }), 200
    finally:
        session.close()


@bp_admin.route("/api/admin/context/rebuild-all", methods=["POST"])
def admin_rebuild_context_all():
    ok, resp = require_admin()
    if not ok:
        return resp

    payload = request.get_json(force=True) or {}
    only_finished = payload.get("only_finished", True)
    limit = payload.get("limit")

    summary = _rebuild_context_all_internal(only_finished=bool(only_finished), limit=limit)
    return jsonify(summary), 200
