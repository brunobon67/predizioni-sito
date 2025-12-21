import os
import sys
import subprocess
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS

from sqlalchemy import create_engine, Column, Integer, String, or_, text
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

def _rebuild_context_all_internal(only_finished: bool = True, limit=None):
    """
    Ricostruisce match_context per tutte le coppie (competition, season).
    Usata internamente dopo /api/admin/import per automatizzare top/mid/bottom + ranking.
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
                session.add(MatchContext(
                    match_id=m.id,
                    competition=comp,
                    season=seas,
                    date=m.date,
                    home_team=m.home_team,
                    away_team=m.away_team,
                    home_rank_before=ranks_before.get(m.home_team, total_teams),
                    away_rank_before=ranks_before.get(m.away_team, total_teams),
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
            results.append({"competition": comp, "season": seas, "inserted": inserted, "total_teams": total_teams})

        return {"ok": True, "only_finished": only_finished, "pairs": len(pairs), "results": results}

    finally:
        session.close()



@app.route("/api/admin/ping", methods=["GET"])
def admin_ping():
    return jsonify({"admin_token_set": bool(os.getenv("ADMIN_TOKEN"))}), 200


@app.route("/api/admin/import", methods=["POST"])
def admin_import():
    ok, resp = require_admin()
    if not ok:
            # AUTO: rebuild context dopo import (così top/mid/bottom + ranking funzionano sempre)
        rebuild_summary = _rebuild_context_all_internal(only_finished=True)

        return jsonify({
            "ok": True,
            "stdout": (result.stdout or "")[-4000:],
            "stderr": (result.stderr or "")[-4000:],
            "context_rebuild": rebuild_summary
        }), 200


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


# -----------------------------
# Admin: DB check
# -----------------------------
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


# -----------------------------
# Admin: Context rebuild (single)
# -----------------------------
@app.route("/api/admin/context/rebuild", methods=["POST"])
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


# -----------------------------
# Admin: Context rebuild (ALL competitions/seasons)
# -----------------------------
@app.route("/api/admin/context/rebuild-all", methods=["POST"])
def admin_rebuild_context_all():
    ok, resp = require_admin()
    if not ok:
        return resp

    payload = request.get_json(force=True) or {}
    only_finished = payload.get("only_finished", True)
    limit = payload.get("limit")  # opzionale per test

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
                session.add(MatchContext(
                    match_id=m.id,
                    competition=comp,
                    season=seas,
                    date=m.date,
                    home_team=m.home_team,
                    away_team=m.away_team,
                    home_rank_before=ranks_before.get(m.home_team, total_teams),
                    away_rank_before=ranks_before.get(m.away_team, total_teams),
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
            results.append({"competition": comp, "season": seas, "inserted": inserted, "total_teams": total_teams})

        return jsonify({
            "ok": True,
            "only_finished": only_finished,
            "pairs": len(pairs),
            "results": results
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
# API: Stats (complete, includes top/mid/bottom + rank bands via MatchContext)
# =============================
@app.route("/api/stats", methods=["GET"])
def get_stats():
    """
    Statistiche calcolate SOLO sulle partite passate (status='FINISHED').

    Parametri:
      - team (obbligatorio): nome squadra (es. "Juventus FC")
      - competition (opzionale): filtra per competizione
      - season (opzionale): stagione (es. 2024)
      - top_n (opzionale): default 6
      - bottom_n (opzionale): default 5
    """
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

        # =========================
        # VS TOP / MID / BOTTOM + RANK BUCKETS
        # =========================
        top_n = request.args.get("top_n", default=6, type=int)
        bottom_n = request.args.get("bottom_n", default=5, type=int)

        vs_rank_groups = {
            "note": "Per calcolare vs_top/vs_mid/vs_bottom e buckets serve selezionare competition e season e avere MatchContext popolato."
        }

        if competition and (season_param is not None):
            season_all = (
                session.query(Match)
                .filter(Match.status == "FINISHED")
                .filter(Match.competition == competition)
                .filter(Match.season == season_param)
                .all()
            )

            teams_set = set()
            for mm in season_all:
                teams_set.add(mm.home_team)
                teams_set.add(mm.away_team)

            total_teams = len(teams_set)
            bottom_threshold = max(1, total_teams - bottom_n + 1)

            match_ids = [m.id for m in matches]
            ctx_rows = (
                session.query(MatchContext)
                .filter(MatchContext.match_id.in_(match_ids))
                .all()
            )
            ctx_by_id = {c.match_id: c for c in ctx_rows}

            def init_bucket():
                return {"w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0}

            def add_result(bucket, gf, ga):
                bucket["gf"] += gf
                bucket["ga"] += ga
                if gf > ga:
                    bucket["w"] += 1
                elif gf == ga:
                    bucket["d"] += 1
                else:
                    bucket["l"] += 1

            def pack_bucket(b):
                mp = b["w"] + b["d"] + b["l"]
                points = b["w"] * 3 + b["d"]
                return {
                    "matches": mp,
                    "wins": b["w"],
                    "draws": b["d"],
                    "losses": b["l"],
                    "points": points,
                    "ppg": (points / mp) if mp else 0.0,
                    "goals_for": b["gf"],
                    "goals_against": b["ga"],
                    "avg_goals_for": (b["gf"] / mp) if mp else 0.0,
                    "avg_goals_against": (b["ga"] / mp) if mp else 0.0,
                    "win_rate": (b["w"] / mp) if mp else 0.0,
                    "draw_rate": (b["d"] / mp) if mp else 0.0,
                    "loss_rate": (b["l"] / mp) if mp else 0.0,
                }

            top_all = init_bucket()
            mid_all = init_bucket()
            bot_all = init_bucket()

            top_home = init_bucket()
            mid_home = init_bucket()
            bot_home = init_bucket()

            top_away = init_bucket()
            mid_away = init_bucket()
            bot_away = init_bucket()

            bucket_size = 5
            rank_bands = []
            start = 1
            while start <= total_teams:
                end = min(total_teams, start + bucket_size - 1)
                rank_bands.append((f"{start}-{end}", start, end))
                start = end + 1

            bands_all = {name: init_bucket() for (name, _, _) in rank_bands}
            bands_home = {name: init_bucket() for (name, _, _) in rank_bands}
            bands_away = {name: init_bucket() for (name, _, _) in rank_bands}

            def band_name_for_rank(rank):
                for (name, a, b) in rank_bands:
                    if a <= rank <= b:
                        return name
                return None

            missing_ctx = 0
            for m in matches:
                ctx = ctx_by_id.get(m.id)
                if not ctx:
                    missing_ctx += 1
                    continue

                is_home = (m.home_team == team)

                hg = m.home_goals or 0
                ag = m.away_goals or 0

                if is_home:
                    gf, ga = hg, ag
                    opp_rank_before = ctx.away_rank_before
                else:
                    gf, ga = ag, hg
                    opp_rank_before = ctx.home_rank_before

                if opp_rank_before <= top_n:
                    add_result(top_all, gf, ga)
                    add_result(top_home if is_home else top_away, gf, ga)
                elif opp_rank_before >= bottom_threshold:
                    add_result(bot_all, gf, ga)
                    add_result(bot_home if is_home else bot_away, gf, ga)
                else:
                    add_result(mid_all, gf, ga)
                    add_result(mid_home if is_home else mid_away, gf, ga)

                bn = band_name_for_rank(opp_rank_before)
                if bn:
                    add_result(bands_all[bn], gf, ga)
                    add_result(bands_home[bn] if is_home else bands_away[bn], gf, ga)

            vs_rank_groups = {
                "top_n": top_n,
                "bottom_n": bottom_n,
                "total_teams": total_teams,
                "bottom_threshold_rank": bottom_threshold,
                "missing_context_rows": missing_ctx,

                "vs_top": pack_bucket(top_all),
                "vs_mid": pack_bucket(mid_all),
                "vs_bottom": pack_bucket(bot_all),

                "home": {
                    "vs_top": pack_bucket(top_home),
                    "vs_mid": pack_bucket(mid_home),
                    "vs_bottom": pack_bucket(bot_home),
                },
                "away": {
                    "vs_top": pack_bucket(top_away),
                    "vs_mid": pack_bucket(mid_away),
                    "vs_bottom": pack_bucket(bot_away),
                },

                "rank_bands": [name for (name, _, _) in rank_bands],
                "bands": {name: pack_bucket(bands_all[name]) for (name, _, _) in rank_bands},
                "bands_home": {name: pack_bucket(bands_home[name]) for (name, _, _) in rank_bands},
                "bands_away": {name: pack_bucket(bands_away[name]) for (name, _, _) in rank_bands},
            }

        # =========================
        # BASE + HOME/AWAY + FORM + O/U + BTTS
        # =========================
        matches_played = len(matches)
        wins = draws = losses = 0
        goals_scored = goals_conceded = 0

        home_matches = home_wins = home_draws = home_losses = 0
        away_matches = away_wins = away_draws = away_losses = 0
        home_gf = home_ga = 0
        away_gf = away_ga = 0

        OU_LINES = [0.5, 1.5, 2.5, 3.5, 4.5]

        def init_ou_dict():
            return {line: {"over": 0, "under": 0} for line in OU_LINES}

        ou_overall = init_ou_dict()
        ou_home = init_ou_dict()
        ou_away = init_ou_dict()

        fts = 0
        home_fts = 0
        away_fts = 0

        over_25 = under_25 = btts = 0
        home_over_25 = home_under_25 = home_btts = 0
        away_over_25 = away_under_25 = away_btts = 0

        results_sequence = []
        home_results_sequence = []
        away_results_sequence = []
        home_matches_list = []
        away_matches_list = []

        for m in matches:
            hg = m.home_goals or 0
            ag = m.away_goals or 0
            total_goals = hg + ag

            if m.home_team == team:
                gf, ga = hg, ag
                is_home_game = True
            else:
                gf, ga = ag, hg
                is_home_game = False

            goals_scored += gf
            goals_conceded += ga

            if gf == 0:
                fts += 1
                if is_home_game:
                    home_fts += 1
                else:
                    away_fts += 1

            if gf > ga:
                wins += 1
                results_sequence.append("W")
                if is_home_game:
                    home_wins += 1
                    home_results_sequence.append("W")
                else:
                    away_wins += 1
                    away_results_sequence.append("W")
            elif gf == ga:
                draws += 1
                results_sequence.append("D")
                if is_home_game:
                    home_draws += 1
                    home_results_sequence.append("D")
                else:
                    away_draws += 1
                    away_results_sequence.append("D")
            else:
                losses += 1
                results_sequence.append("L")
                if is_home_game:
                    home_losses += 1
                    home_results_sequence.append("L")
                else:
                    away_losses += 1
                    away_results_sequence.append("L")

            if is_home_game:
                home_matches += 1
                home_gf += gf
                home_ga += ga
                home_matches_list.append(m)
            else:
                away_matches += 1
                away_gf += gf
                away_ga += ga
                away_matches_list.append(m)

            for line in OU_LINES:
                if total_goals > line:
                    ou_overall[line]["over"] += 1
                else:
                    ou_overall[line]["under"] += 1

            target = ou_home if is_home_game else ou_away
            for line in OU_LINES:
                if total_goals > line:
                    target[line]["over"] += 1
                else:
                    target[line]["under"] += 1

            if total_goals > 2.5:
                over_25 += 1
            else:
                under_25 += 1

            if hg > 0 and ag > 0:
                btts += 1

            if is_home_game:
                if total_goals > 2.5:
                    home_over_25 += 1
                else:
                    home_under_25 += 1
                if hg > 0 and ag > 0:
                    home_btts += 1
            else:
                if total_goals > 2.5:
                    away_over_25 += 1
                else:
                    away_under_25 += 1
                if hg > 0 and ag > 0:
                    away_btts += 1

        goal_difference = goals_scored - goals_conceded
        avg_scored = goals_scored / matches_played if matches_played else 0.0
        avg_conceded = goals_conceded / matches_played if matches_played else 0.0
        avg_total_goals = (goals_scored + goals_conceded) / matches_played if matches_played else 0.0

        win_rate = wins / matches_played if matches_played else 0.0
        draw_rate = draws / matches_played if matches_played else 0.0
        loss_rate = losses / matches_played if matches_played else 0.0

        home_win_rate = home_wins / home_matches if home_matches else 0.0
        home_draw_rate = home_draws / home_matches if home_matches else 0.0
        home_loss_rate = home_losses / home_matches if home_matches else 0.0

        away_win_rate = away_wins / away_matches if away_matches else 0.0
        away_draw_rate = away_draws / away_matches if away_matches else 0.0
        away_loss_rate = away_losses / away_matches if away_matches else 0.0

        home_avg_total_goals = (home_gf + home_ga) / home_matches if home_matches else 0.0
        away_avg_total_goals = (away_gf + away_ga) / away_matches if away_matches else 0.0

        def form_block(seq_source, match_list, last_n: int):
            seq = seq_source[-last_n:] if last_n else []
            w = seq.count("W")
            d = seq.count("D")
            l = seq.count("L")
            points = w * 3 + d

            gf_sum = ga_sum = 0
            last_matches = match_list[-last_n:] if last_n else []
            for mm in last_matches:
                hg = mm.home_goals or 0
                ag = mm.away_goals or 0
                if mm.home_team == team:
                    gf_sum += hg
                    ga_sum += ag
                else:
                    gf_sum += ag
                    ga_sum += hg

            return {
                "record": f"{w}W-{d}D-{l}L",
                "wins": w,
                "draws": d,
                "losses": l,
                "points": points,
                "goals_scored": gf_sum,
                "goals_conceded": ga_sum,
            }

        form_last_5 = form_block(results_sequence, matches, 5)
        form_last_10 = form_block(results_sequence, matches, 10)

        home_form_last_5 = form_block(home_results_sequence, home_matches_list, 5)
        home_form_last_10 = form_block(home_results_sequence, home_matches_list, 10)

        away_form_last_5 = form_block(away_results_sequence, away_matches_list, 5)
        away_form_last_10 = form_block(away_results_sequence, away_matches_list, 10)

        def pack_over_under_multiline(ou_dict, mp, btts_count, legacy_over25=None, legacy_under25=None):
            out = {
                "btts": btts_count,
                "btts_rate": (btts_count / mp) if mp else 0.0,
                "lines": {}
            }
            for line, v in ou_dict.items():
                over_cnt = v["over"]
                under_cnt = v["under"]
                key = str(line).replace(".", "_")
                out["lines"][key] = {
                    "line": line,
                    "over": over_cnt,
                    "under": under_cnt,
                    "over_rate": (over_cnt / mp) if mp else 0.0,
                    "under_rate": (under_cnt / mp) if mp else 0.0,
                }
            if legacy_over25 is not None and legacy_under25 is not None:
                out["over_25"] = legacy_over25
                out["under_25"] = legacy_under25
                out["over_25_rate"] = (legacy_over25 / mp) if mp else 0.0
                out["under_25_rate"] = (legacy_under25 / mp) if mp else 0.0
            return out

        stats = {
            "team": team,
            "competition": competition if competition else "All",
            "season": season_param if season_param is not None else "All",

            "matches_played": matches_played,
            "wins": wins,
            "draws": draws,
            "losses": losses,

            "goals_scored": goals_scored,
            "goals_conceded": goals_conceded,

            "win_rate": win_rate,
            "draw_rate": draw_rate,
            "loss_rate": loss_rate,

            "home_win_rate": home_win_rate,
            "away_win_rate": away_win_rate,

            "failed_to_score": {
                "count": fts,
                "rate": (fts / matches_played) if matches_played else 0.0
            },

            "goals": {
                "scored": goals_scored,
                "conceded": goals_conceded,
                "goal_difference": goal_difference,
                "avg_scored": avg_scored,
                "avg_conceded": avg_conceded,
                "avg_total_goals": avg_total_goals,
            },

            "over_under": pack_over_under_multiline(
                ou_overall, matches_played, btts,
                legacy_over25=over_25, legacy_under25=under_25
            ),

            "home": {
                "matches": home_matches,
                "wins": home_wins,
                "draws": home_draws,
                "losses": home_losses,
                "win_rate": home_win_rate,
                "draw_rate": home_draw_rate,
                "loss_rate": home_loss_rate,

                "goals_scored": home_gf,
                "goals_conceded": home_ga,
                "avg_scored": (home_gf / home_matches) if home_matches else 0.0,
                "avg_conceded": (home_ga / home_matches) if home_matches else 0.0,
                "avg_total_goals": home_avg_total_goals,

                "failed_to_score": {
                    "count": home_fts,
                    "rate": (home_fts / home_matches) if home_matches else 0.0
                },

                "over_under": pack_over_under_multiline(
                    ou_home, home_matches, home_btts,
                    legacy_over25=home_over_25, legacy_under25=home_under_25
                ),
                "form": {"last_5": home_form_last_5, "last_10": home_form_last_10},
            },

            "away": {
                "matches": away_matches,
                "wins": away_wins,
                "draws": away_draws,
                "losses": away_losses,
                "win_rate": away_win_rate,
                "draw_rate": away_draw_rate,
                "loss_rate": away_loss_rate,

                "goals_scored": away_gf,
                "goals_conceded": away_ga,
                "avg_scored": (away_gf / away_matches) if away_matches else 0.0,
                "avg_conceded": (away_ga / away_matches) if away_matches else 0.0,
                "avg_total_goals": away_avg_total_goals,

                "failed_to_score": {
                    "count": away_fts,
                    "rate": (away_fts / away_matches) if away_matches else 0.0
                },

                "over_under": pack_over_under_multiline(
                    ou_away, away_matches, away_btts,
                    legacy_over25=away_over_25, legacy_under25=away_under_25
                ),
                "form": {"last_5": away_form_last_5, "last_10": away_form_last_10},
            },

            "form": {
                "last_5": form_last_5,
                "last_10": form_last_10,
            },

            "vs_rank_groups": vs_rank_groups,
        }

        return jsonify(stats)
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
