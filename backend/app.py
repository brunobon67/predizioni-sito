# =============================
# Imports base
# =============================
from flask import Flask, request, jsonify
from flask_cors import CORS

import os
from sqlalchemy import create_engine, Column, Integer, String, or_
from sqlalchemy.orm import sessionmaker, declarative_base

# =============================
# Flask app
# =============================
app = Flask(__name__)

# =============================
# CORS (Netlify + locale)
# =============================
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "https://predizioni-sito.netlify.app",
            "http://localhost:5500",
            "http://127.0.0.1:5500"
        ]
    }
})

# =============================
# Database config (SQLite locale / Postgres Render)
# =============================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///calcio.db")

# Render può fornire postgres:// (deprecato)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    competition = Column(String, nullable=False)
    home_team = Column(String, nullable=False)
    away_team = Column(String, nullable=False)
    date = Column(String, nullable=False)  # es. "2025-01-15"
    status = Column(String, nullable=False)  # "FINISHED", "UPCOMING", ecc.
    home_goals = Column(Integer, nullable=True)
    away_goals = Column(Integer, nullable=True)
    season = Column(Integer, nullable=True)  # es. 2024, 2025


class MatchContext(Base):
    __tablename__ = "match_context"

    match_id = Column(Integer, primary_key=True, index=True)

    competition = Column(String, nullable=False)
    season = Column(Integer, nullable=False)
    date = Column(String, nullable=False)

    home_team = Column(String, nullable=False)
    away_team = Column(String, nullable=False)

    home_rank_before = Column(Integer, nullable=False)
    away_rank_before = Column(Integer, nullable=False)

    total_teams = Column(Integer, nullable=False)


Base.metadata.create_all(bind=engine)

# -----------------------------
# Utility: init info
# -----------------------------
def db_info():
    session = SessionLocal()
    try:
        count = session.query(Match).count()
        print(f"✅ Database inizializzato, partite presenti: {count}")
    finally:
        session.close()


db_info()

# -----------------------------
# API: Teams (filtered)
# -----------------------------
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

        teams = sorted(list(teams_set))
        return jsonify({"teams": teams})
    finally:
        session.close()


# -----------------------------
# API: Matches (for predictions page)
# -----------------------------
@app.route("/api/matches", methods=["GET"])
def get_matches():
    session = SessionLocal()
    try:
        matches = (
            session.query(Match)
            .filter(Match.status != "FINISHED")  # future or not finished
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
            }
            for m in matches
        ]

        return jsonify({"matches": results})
    finally:
        session.close()


# -----------------------------
# API: Stats
# -----------------------------
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

        # filtri
        if competition:
            q = q.filter(Match.competition == competition)
        if season_param is not None:
            q = q.filter(Match.season == season_param)

        q = q.filter(or_(Match.home_team == team, Match.away_team == team))

        matches = q.order_by(Match.date.asc()).all()

        # =========================
        # VS TOP/BOTTOM (rank al momento)
        # =========================
       # =========================
# VS TOP/MID/BOTTOM + BUCKETS (rank al momento)
# =========================
        # =========================
        # VS TOP / MID / BOTTOM + RANK BUCKETS (rank al momento)
        # =========================
        top_n = request.args.get("top_n", default=6, type=int)
        bottom_n = request.args.get("bottom_n", default=5, type=int)

        vs_rank_groups = {
            "note": "Per calcolare vs_top/vs_mid/vs_bottom e buckets serve selezionare competition e season."
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

            # ---------- helpers ----------
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

            # ---------- TOP / MID / BOTTOM ----------
            top_all = init_bucket()
            mid_all = init_bucket()
            bot_all = init_bucket()

            top_home = init_bucket()
            mid_home = init_bucket()
            bot_home = init_bucket()

            top_away = init_bucket()
            mid_away = init_bucket()
            bot_away = init_bucket()

            # ---------- RANK BANDS (1-5 / 6-10 / ...) ----------
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

            # ---------- loop match ----------
            for m in matches:
                ctx = ctx_by_id.get(m.id)
                if not ctx:
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

                # fascia
                if opp_rank_before <= top_n:
                    add_result(top_all, gf, ga)
                    add_result(top_home if is_home else top_away, gf, ga)
                elif opp_rank_before >= bottom_threshold:
                    add_result(bot_all, gf, ga)
                    add_result(bot_home if is_home else bot_away, gf, ga)
                else:
                    add_result(mid_all, gf, ga)
                    add_result(mid_home if is_home else mid_away, gf, ga)

                # bucket ranking
                bn = band_name_for_rank(opp_rank_before)
                if bn:
                    add_result(bands_all[bn], gf, ga)
                    add_result(bands_home[bn] if is_home else bands_away[bn], gf, ga)

            vs_rank_groups = {
                "top_n": top_n,
                "bottom_n": bottom_n,
                "total_teams": total_teams,
                "bottom_threshold_rank": bottom_threshold,

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

        # ===== CALCOLI BASE =====
        matches_played = len(matches)
        wins = draws = losses = 0
        goals_scored = goals_conceded = 0

        # HOME/AWAY breakdown
        home_matches = home_wins = home_draws = home_losses = 0
        away_matches = away_wins = away_draws = away_losses = 0
        home_gf = home_ga = 0
        away_gf = away_ga = 0

        # ---------- NUOVE STATS: Over/Under multi-line ----------
        OU_LINES = [0.5, 1.5, 2.5, 3.5, 4.5]

        def init_ou_dict():
            return {line: {"over": 0, "under": 0} for line in OU_LINES}

        ou_overall = init_ou_dict()
        ou_home = init_ou_dict()
        ou_away = init_ou_dict()

        # ---------- Failed to score ----------
        fts = 0
        home_fts = 0
        away_fts = 0

        # Over/Under & BTTS (legacy overall: 2.5)
        over_25 = under_25 = btts = 0

        # Over/Under & BTTS (legacy home/away split: 2.5)
        home_over_25 = home_under_25 = home_btts = 0
        away_over_25 = away_under_25 = away_btts = 0

        # per forma (overall)
        results_sequence = []  # 'W'/'D'/'L' ordinati per data

        # per forma split
        home_results_sequence = []
        away_results_sequence = []
        home_matches_list = []
        away_matches_list = []

        for m in matches:
            hg = m.home_goals or 0
            ag = m.away_goals or 0
            total_goals = hg + ag

            # goals (from team perspective)
            if m.home_team == team:
                gf, ga = hg, ag
                is_home_game = True
            else:
                gf, ga = ag, hg
                is_home_game = False

            goals_scored += gf
            goals_conceded += ga

            # Failed to score
            if gf == 0:
                fts += 1
                if is_home_game:
                    home_fts += 1
                else:
                    away_fts += 1

            # W/D/L
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

            # home/away counts & goals
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

            # ---------- Over/Under multi-line (overall + split) ----------
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

            # ---------- Legacy Over/Under 2.5 (overall) ----------
            if total_goals > 2.5:
                over_25 += 1
            else:
                under_25 += 1

            # BTTS (overall)
            if hg > 0 and ag > 0:
                btts += 1

            # legacy split over/under + btts
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

        # derived overall
        goal_difference = goals_scored - goals_conceded
        avg_scored = goals_scored / matches_played if matches_played else 0.0
        avg_conceded = goals_conceded / matches_played if matches_played else 0.0
        avg_total_goals = (goals_scored + goals_conceded) / matches_played if matches_played else 0.0

        # rates overall
        win_rate = wins / matches_played if matches_played else 0.0
        draw_rate = draws / matches_played if matches_played else 0.0
        loss_rate = losses / matches_played if matches_played else 0.0

        # rates home/away (WDL)
        home_win_rate = home_wins / home_matches if home_matches else 0.0
        home_draw_rate = home_draws / home_matches if home_matches else 0.0
        home_loss_rate = home_losses / home_matches if home_matches else 0.0

        away_win_rate = away_wins / away_matches if away_matches else 0.0
        away_draw_rate = away_draws / away_matches if away_matches else 0.0
        away_loss_rate = away_losses / away_matches if away_matches else 0.0

        home_avg_total_goals = (home_gf + home_ga) / home_matches if home_matches else 0.0
        away_avg_total_goals = (away_gf + away_ga) / away_matches if away_matches else 0.0

        # form (overall)
        def form_block(last_n: int):
            seq = results_sequence[-last_n:] if last_n else []
            w = seq.count("W")
            d = seq.count("D")
            l = seq.count("L")
            points = w * 3 + d

            gf_sum = ga_sum = 0
            last_matches = matches[-last_n:] if last_n else []
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

        # form (home/away)
        def form_block_from(seq_source, match_list, last_n: int):
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

        form_last_5 = form_block(5)
        form_last_10 = form_block(10)

        home_form_last_5 = form_block_from(home_results_sequence, home_matches_list, 5)
        home_form_last_10 = form_block_from(home_results_sequence, home_matches_list, 10)

        away_form_last_5 = form_block_from(away_results_sequence, away_matches_list, 5)
        away_form_last_10 = form_block_from(away_results_sequence, away_matches_list, 10)

        # helpers
        def pack_over_under_multiline(ou_dict, mp, btts_count, legacy_over25=None, legacy_under25=None):
            out = {
                "btts": btts_count,
                "btts_rate": (btts_count / mp) if mp else 0.0,
                "lines": {}
            }

            for line, v in ou_dict.items():
                over_cnt = v["over"]
                under_cnt = v["under"]
                key = str(line).replace(".", "_")  # 2.5 -> "2_5"
                out["lines"][key] = {
                    "line": line,
                    "over": over_cnt,
                    "under": under_cnt,
                    "over_rate": (over_cnt / mp) if mp else 0.0,
                    "under_rate": (under_cnt / mp) if mp else 0.0,
                }

            # retrocompat: over_25 / under_25
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

            # base
            "matches_played": matches_played,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "goals_scored": goals_scored,
            "goals_conceded": goals_conceded,

            # rates overall
            "win_rate": win_rate,
            "draw_rate": draw_rate,
            "loss_rate": loss_rate,

            # existing rates (kept)
            "home_win_rate": home_win_rate,
            "away_win_rate": away_win_rate,

            # NEW: failed to score
            "failed_to_score": {
                "count": fts,
                "rate": (fts / matches_played) if matches_played else 0.0
            },

            # breakdown objects
            "goals": {
                "scored": goals_scored,
                "conceded": goals_conceded,
                "goal_difference": goal_difference,
                "avg_scored": avg_scored,
                "avg_conceded": avg_conceded,
                "avg_total_goals": avg_total_goals,  # NEW
            },

            # NEW: over/under multiline + legacy 2.5
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
                "avg_total_goals": home_avg_total_goals,  # NEW

                "failed_to_score": {  # NEW
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
                "avg_total_goals": away_avg_total_goals,  # NEW

                "failed_to_score": {  # NEW
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


# -----------------------------
# API: Standings (NEW)
# -----------------------------
@app.route("/api/standings", methods=["GET"])
def get_standings():
    """
    Classifica dinamica (standings) calcolata dalle partite FINISHED fino ad una certa data.

    Query params:
      - competition (required)
      - season (required, int)
      - date (required, YYYY-MM-DD) -> include tutte le partite con Match.date <= date
    """
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

        # tie-break: points, gd, gf, played, name
        rows.sort(key=lambda r: (r["points"], r["gd"], r["gf"], r["played"], r["team"]), reverse=True)

        for i, r in enumerate(rows, start=1):
            r["rank"] = i

        return jsonify({
            "competition": competition,
            "season": season,
            "date": date_limit,
            "standings": rows
        })
    finally:
        session.close()


# -----------------------------
# API: Predict
# -----------------------------
@app.route("/api/predict", methods=["POST"])
def predict_match():
    """
    Endpoint per le previsioni sulle partite FUTURE.
    In input:
    {
        "match_id": 101,
        "model": "modello_base"
    }
    """
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

        probabilities = {
            "home_win": 0.40,
            "draw": 0.30,
            "away_win": 0.30,
            "explanation": f"Modello: {model}. Placeholder: integra qui il tuo motore predittivo."
        }

        return jsonify({
            "match_id": match_id,
            "model": model,
            "probabilities": probabilities
        })
    finally:
        session.close()

# -----------------------------
# API: Admin – Update matches
# -----------------------------
import subprocess
import sys
from pathlib import Path

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

@app.post("/api/admin/update-matches")
def update_matches():
    token = request.headers.get("X-Admin-Token")

    if not ADMIN_TOKEN:
        return jsonify({"error": "missing ADMIN_TOKEN env var"}), 500

    if token != ADMIN_TOKEN:
        return jsonify({"error": "unauthorized"}), 401

    try:
        # app.py è in backend/, quindi update_leagues.py è nello stesso folder
        script_path = Path(__file__).resolve().parent / "update_leagues.py"
        subprocess.Popen([sys.executable, str(script_path)])
        return jsonify({"status": "started"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500




if __name__ == "__main__":
    app.run(debug=True)


@app.get("/api/admin/ping")
def admin_ping():
    return jsonify({"admin_token_set": bool(os.getenv("ADMIN_TOKEN"))}), 200


import os
import subprocess
from flask import request, jsonify

@app.route("/api/admin/import", methods=["POST"])
def admin_import():
    token = os.getenv("ADMIN_TOKEN", "")
    req_token = request.headers.get("X-Admin-Token", "")

    if not token or req_token != token:
        return jsonify({"error": "Unauthorized"}), 401

    # esegue lo script di import dentro Render (DB interno accessibile)
    try:
        result = subprocess.run(
            ["python", "backend/update_leagues.py"],
            capture_output=True,
            text=True,
            check=True
        )
        return jsonify({
            "ok": True,
            "stdout": result.stdout[-4000:],  # limita output
            "stderr": result.stderr[-4000:]
        })
    except subprocess.CalledProcessError as e:
        return jsonify({
            "ok": False,
            "stdout": (e.stdout or "")[-4000:],
            "stderr": (e.stderr or "")[-4000:],
        }), 500

