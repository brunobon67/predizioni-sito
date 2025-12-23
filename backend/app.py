import os
import sys
import subprocess
import math
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


# =============================
# Rule-based predictor (points/weights) for 1X2
# =============================
def _safe_div(a: float, b: float) -> float:
    return float(a) / float(b) if b else 0.0


def _softmax3(a: float, b: float, c: float):
    m = max(a, b, c)
    ea = math.exp(a - m)
    eb = math.exp(b - m)
    ec = math.exp(c - m)
    s = ea + eb + ec
    return ea / s, eb / s, ec / s


def _points_from_result(gf: int, ga: int) -> int:
    if gf > ga:
        return 3
    if gf == ga:
        return 1
    return 0


def _get_ctx(session, match_id: int):
    return session.query(MatchContext).filter(MatchContext.match_id == match_id).first()


def _team_past_matches(session, team: str, competition: str, season: int, date_cutoff: str):
    return (
        session.query(Match)
        .filter(Match.status == "FINISHED")
        .filter(Match.competition == competition)
        .filter(Match.season == season)
        .filter(Match.date < date_cutoff)
        .filter(or_(Match.home_team == team, Match.away_team == team))
        .order_by(Match.date.asc(), Match.id.asc())
        .all()
    )


def _compute_basic_splits(team: str, matches):
    def init():
        return {"mp": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0, "seq_pts": []}

    overall = init()
    home = init()
    away = init()

    for m in matches:
        hg = m.home_goals or 0
        ag = m.away_goals or 0
        is_home = (m.home_team == team)

        if is_home:
            gf, ga = hg, ag
            bucket = home
        else:
            gf, ga = ag, hg
            bucket = away

        for b in (overall, bucket):
            b["mp"] += 1
            b["gf"] += gf
            b["ga"] += ga
            pts = _points_from_result(gf, ga)
            b["pts"] += pts
            b["seq_pts"].append(pts)
            if gf > ga:
                b["w"] += 1
            elif gf == ga:
                b["d"] += 1
            else:
                b["l"] += 1

    def pack(b):
        mp = b["mp"]
        return {
            "matches": mp,
            "wins": b["w"],
            "draws": b["d"],
            "losses": b["l"],
            "win_rate": _safe_div(b["w"], mp),
            "draw_rate": _safe_div(b["d"], mp),
            "loss_rate": _safe_div(b["l"], mp),
            "ppg": _safe_div(b["pts"], mp),
            "avg_gf": _safe_div(b["gf"], mp),
            "avg_ga": _safe_div(b["ga"], mp),
        }

    out = {"overall": pack(overall), "home": pack(home), "away": pack(away)}
    last5 = overall["seq_pts"][-5:]
    out["overall"]["last5_ppg"] = _safe_div(sum(last5), len(last5)) if last5 else 0.0
    return out


def _band_label(total_teams: int, rank: int, band_size: int = 5) -> str:
    if not total_teams or not rank:
        return "unknown"
    start = ((rank - 1) // band_size) * band_size + 1
    end = min(total_teams, start + band_size - 1)
    return f"{start}-{end}"


def _compute_vs_opponent_band_ppg(
    session,
    team: str,
    competition: str,
    season: int,
    date_cutoff: str,
    opponent_rank_before: int,
    total_teams: int,
    band_size: int = 5
):
    if not opponent_rank_before or not total_teams:
        return 0.0, 0.0, 0.0, 0, 0, 0

    target_band = _band_label(total_teams, opponent_rank_before, band_size)

    matches = _team_past_matches(session, team, competition, season, date_cutoff)
    if not matches:
        return 0.0, 0.0, 0.0, 0, 0, 0

    ids = [m.id for m in matches]
    ctx_rows = session.query(MatchContext).filter(MatchContext.match_id.in_(ids)).all()
    ctx_by_id = {c.match_id: c for c in ctx_rows}

    def init():
        return {"mp": 0, "pts": 0}

    o = init()
    h = init()
    a = init()

    for m in matches:
        ctx = ctx_by_id.get(m.id)
        if not ctx:
            continue

        hg = m.home_goals or 0
        ag = m.away_goals or 0
        is_home = (m.home_team == team)

        if is_home:
            gf, ga = hg, ag
            opp_rank = ctx.away_rank_before
            bucket = h
        else:
            gf, ga = ag, hg
            opp_rank = ctx.home_rank_before
            bucket = a

        b = _band_label(total_teams, opp_rank, band_size)
        if b != target_band:
            continue

        pts = _points_from_result(gf, ga)
        o["mp"] += 1
        o["pts"] += pts
        bucket["mp"] += 1
        bucket["pts"] += pts

    return (
        _safe_div(o["pts"], o["mp"]),
        _safe_div(h["pts"], h["mp"]),
        _safe_div(a["pts"], a["mp"]),
        o["mp"], h["mp"], a["mp"]
    )


def predict_rule_based(match_id: int, weights: dict | None = None) -> dict:
    """
    Modello a punteggio (trasparente) che usa:
    - ranking prima del match (match_context)
    - performance casa/trasferta
    - performance vs fascia ranking dell'avversario (bands) con split casa/trasferta
    - gol fatti/subiti (casa vs trasferta)
    - forma ultime 5 (PPG)
    """
    W = {
        "rank_pos_weight": 0.50,

        "home_win_weight": 3.0,
        "home_loss_weight": 2.0,
        "away_win_weight": 3.0,
        "away_loss_weight": 2.0,

        "vs_band_weight": 2.0,
        "vs_band_home_weight": 1.0,
        "vs_band_away_weight": 1.0,

        "gf_diff_weight": 1.5,
        "ga_diff_weight": 1.2,

        "last5_ppg_weight": 0.8,

        "draw_base": 3.2,
    }
    if weights:
        W.update(weights)

    session = SessionLocal()
    try:
        m = session.query(Match).filter(Match.id == match_id).first()
        if not m:
            return {"ok": False, "error": "Match non trovato", "match_id": int(match_id)}

        if m.season is None:
            return {"ok": False, "error": "Match.season mancante", "match_id": int(match_id)}

        competition = m.competition
        season = int(m.season)
        date_cutoff = m.date
        home_team = m.home_team
        away_team = m.away_team

        ctx = _get_ctx(session, m.id)
        if not ctx:
            # fallback neutro (meglio di crashare)
            total_teams = 20
            home_rank_before = total_teams // 2
            away_rank_before = total_teams // 2
        else:
            total_teams = ctx.total_teams
            home_rank_before = ctx.home_rank_before
            away_rank_before = ctx.away_rank_before

        home_hist = _team_past_matches(session, home_team, competition, season, date_cutoff)
        away_hist = _team_past_matches(session, away_team, competition, season, date_cutoff)

        home_stats = _compute_basic_splits(home_team, home_hist)
        away_stats = _compute_basic_splits(away_team, away_hist)

        # PPG vs band dell'avversario (overall + split)
        home_vs_ppg, home_vs_home_ppg, home_vs_away_ppg, hv_mp, hv_hmp, hv_amp = _compute_vs_opponent_band_ppg(
            session=session,
            team=home_team,
            competition=competition,
            season=season,
            date_cutoff=date_cutoff,
            opponent_rank_before=away_rank_before,
            total_teams=total_teams,
            band_size=5
        )
        away_vs_ppg, away_vs_home_ppg, away_vs_away_ppg, av_mp, av_hmp, av_amp = _compute_vs_opponent_band_ppg(
            session=session,
            team=away_team,
            competition=competition,
            season=season,
            date_cutoff=date_cutoff,
            opponent_rank_before=home_rank_before,
            total_teams=total_teams,
            band_size=5
        )

        # 1) Rank score
        rank_diff = (away_rank_before - home_rank_before)  # positivo se home meglio (rank più basso)
        rank_score = rank_diff * W["rank_pos_weight"]

        # 2) Home performance (home team at home)
        hp = home_stats["home"]
        home_perf_score = (hp["win_rate"] * W["home_win_weight"]) - (hp["loss_rate"] * W["home_loss_weight"])

        # 3) Away performance (away team away) -> sottraiamo
        ap = away_stats["away"]
        away_perf_score = (ap["win_rate"] * W["away_win_weight"]) - (ap["loss_rate"] * W["away_loss_weight"])

        # 4) vs opponent band (overall + split)
        vs_score = (
            (home_vs_ppg - away_vs_ppg) * W["vs_band_weight"]
            + (home_vs_home_ppg - away_vs_home_ppg) * W["vs_band_home_weight"]
            + (home_vs_away_ppg - away_vs_away_ppg) * W["vs_band_away_weight"]
        )

        # 5) Goals (home home vs away away)
        gf_diff = (hp["avg_gf"] - ap["avg_gf"])
        ga_diff = (ap["avg_ga"] - hp["avg_ga"])  # positivo se away concede più di home
        goals_score = (gf_diff * W["gf_diff_weight"]) + (ga_diff * W["ga_diff_weight"])

        # 6) Last 5 form (PPG)
        form_diff = (home_stats["overall"]["last5_ppg"] - away_stats["overall"]["last5_ppg"])
        form_score = form_diff * W["last5_ppg_weight"]

        # Total score
        home_score = (
            rank_score
            + home_perf_score
            - away_perf_score
            + vs_score
            + goals_score
            + form_score
        )

        # Draw: più probabile se i punteggi sono vicini
        draw_score = max(0.2, W["draw_base"] - 0.7 * abs(home_score))

        p_home, p_draw, p_away = _softmax3(home_score, draw_score, -home_score)

        return {
            "ok": True,
            "match_id": int(m.id),
            "competition": competition,
            "season": season,
            "date": date_cutoff,
            "home_team": home_team,
            "away_team": away_team,
            "model": "rules_v1",
            "probabilities": {
                "home_win": p_home,
                "draw": p_draw,
                "away_win": p_away,
            },
            "debug": {
                "ranks": {
                    "home_rank_before": home_rank_before,
                    "away_rank_before": away_rank_before,
                    "total_teams": total_teams,
                    "rank_diff": rank_diff,
                },
                "components": {
                    "rank_score": rank_score,
                    "home_perf_score": home_perf_score,
                    "away_perf_score_subtracted": -away_perf_score,
                    "vs_score": vs_score,
                    "goals_score": goals_score,
                    "form_score": form_score,
                    "home_score_total": home_score,
                    "draw_score": draw_score,
                },
                "inputs": {
                    "home_home": hp,
                    "away_away": ap,
                    "home_last5_ppg": home_stats["overall"]["last5_ppg"],
                    "away_last5_ppg": away_stats["overall"]["last5_ppg"],
                    "home_vs_band": {
                        "ppg_overall": home_vs_ppg,
                        "ppg_home": home_vs_home_ppg,
                        "ppg_away": home_vs_away_ppg,
                        "matches_overall": hv_mp,
                        "matches_home": hv_hmp,
                        "matches_away": hv_amp,
                    },
                    "away_vs_band": {
                        "ppg_overall": away_vs_ppg,
                        "ppg_home": away_vs_home_ppg,
                        "ppg_away": away_vs_away_ppg,
                        "matches_overall": av_mp,
                        "matches_home": av_hmp,
                        "matches_away": av_amp,
                    },
                },
            },
        }
    finally:
        session.close()


# =============================
# Admin endpoints
# =============================
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

        # AUTO rebuild dopo import (così top/mid/bottom + ranking funzionano sempre)
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


@app.route("/api/admin/update-matches", methods=["POST"])
def admin_update_matches():
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
    limit = payload.get("limit")

    summary = _rebuild_context_all_internal(only_finished=bool(only_finished), limit=limit)
    return jsonify(summary), 200


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
# API: Stats
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
            for mm in matches:
                ctx = ctx_by_id.get(mm.id)
                if not ctx:
                    missing_ctx += 1
                    continue

                is_home = (mm.home_team == team)
                hg = mm.home_goals or 0
                ag = mm.away_goals or 0

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

        for mm in matches:
            hg = mm.home_goals or 0
            ag = mm.away_goals or 0
            total_goals = hg + ag

            if mm.home_team == team:
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
                home_matches_list.append(mm)
            else:
                away_matches += 1
                away_gf += gf
                away_ga += ga
                away_matches_list.append(mm)

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
            for mmm in last_matches:
                hg2 = mmm.home_goals or 0
                ag2 = mmm.away_goals or 0
                if mmm.home_team == team:
                    gf_sum += hg2
                    ga_sum += ag2
                else:
                    gf_sum += ag2
                    ga_sum += hg2

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
            out = {"btts": btts_count, "btts_rate": (btts_count / mp) if mp else 0.0, "lines": {}}
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

            "failed_to_score": {"count": fts, "rate": (fts / matches_played) if matches_played else 0.0},

            "goals": {
                "scored": goals_scored,
                "conceded": goals_conceded,
                "goal_difference": goal_difference,
                "avg_scored": avg_scored,
                "avg_conceded": avg_conceded,
                "avg_total_goals": avg_total_goals,
            },

            "over_under": pack_over_under_multiline(ou_overall, matches_played, btts, legacy_over25=over_25, legacy_under25=under_25),

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
                "failed_to_score": {"count": home_fts, "rate": (home_fts / home_matches) if home_matches else 0.0},
                "over_under": pack_over_under_multiline(ou_home, home_matches, home_btts, legacy_over25=home_over_25, legacy_under25=home_under_25),
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
                "failed_to_score": {"count": away_fts, "rate": (away_fts / away_matches) if away_matches else 0.0},
                "over_under": pack_over_under_multiline(ou_away, away_matches, away_btts, legacy_over25=away_over_25, legacy_under25=away_under_25),
                "form": {"last_5": away_form_last_5, "last_10": away_form_last_10},
            },

            "form": {"last_5": form_last_5, "last_10": form_last_10},
            "vs_rank_groups": vs_rank_groups,
        }

        return jsonify(stats)
    finally:
        session.close()


# =============================
# API: Standings
# =============================
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
                table[team_name] = {"team": team_name, "points": 0, "played": 0, "wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0}

        for mm in matches:
            home, away = mm.home_team, mm.away_team
            hg, ag = mm.home_goals or 0, mm.away_goals or 0

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


# =============================
# API: Predict (rule-based)
# =============================
@app.route("/api/predict", methods=["POST"])
def predict_match():
    data = request.get_json(force=True) or {}
    match_id = data.get("match_id")
    model = data.get("model", "rules_v1")

    if not match_id:
        return jsonify({"error": "match_id obbligatorio"}), 400

    if model not in ("rules_v1", "rules"):
        return jsonify({"error": f"model non supportato: {model}"}), 400

    out = predict_rule_based(int(match_id))
    return jsonify(out), (200 if out.get("ok") else 400)


if __name__ == "__main__":
    app.run(debug=True)
