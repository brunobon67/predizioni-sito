from flask import Flask, request, jsonify
from flask_cors import CORS

from sqlalchemy import create_engine, Column, Integer, String, or_
from sqlalchemy.orm import sessionmaker, declarative_base

# -----------------------------
# Configurazione Flask
# -----------------------------
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# -----------------------------
# Configurazione DATABASE (SQLite)
# -----------------------------
DATABASE_URL = "sqlite:///calcio.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

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
        q = session.query(Match).filter(Match.status == "FINISHED")

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
        top_n = request.args.get("top_n", default=6, type=int)
        bottom_n = request.args.get("bottom_n", default=5, type=int)

        vs_rank_groups = {
            "note": "Per calcolare vs_top/vs_bottom serve selezionare competition e season."
        }

        if competition and (season_param is not None):
            # numero squadre della lega+stagione (dalle partite finite)
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

            top_w = top_d = top_l = 0
            bottom_w = bottom_d = bottom_l = 0

            home_top_w = home_top_d = home_top_l = 0
            home_bottom_w = home_bottom_d = home_bottom_l = 0
            away_top_w = away_top_d = away_top_l = 0
            away_bottom_w = away_bottom_d = away_bottom_l = 0

            for m in matches:
                ctx = ctx_by_id.get(m.id)
                if not ctx:
                    continue

                # True se la squadra richiesta gioca in casa in questa partita
                is_home = (m.home_team == team)

                hg = m.home_goals or 0
                ag = m.away_goals or 0

                # team goals & opponent goals
                if m.home_team == team:
                    team_goals, opp_goals = hg, ag
                    opp_rank_before = ctx.away_rank_before
                else:
                    team_goals, opp_goals = ag, hg
                    opp_rank_before = ctx.home_rank_before

                # vs TOP
                if opp_rank_before <= top_n:
                    if team_goals > opp_goals:
                        top_w += 1
                        if is_home:
                            home_top_w += 1
                        else:
                            away_top_w += 1
                    elif team_goals == opp_goals:
                        top_d += 1
                        if is_home:
                            home_top_d += 1
                        else:
                            away_top_d += 1
                    else:
                        top_l += 1
                        if is_home:
                            home_top_l += 1
                        else:
                            away_top_l += 1

                # vs BOTTOM
                if opp_rank_before >= bottom_threshold:
                    if team_goals > opp_goals:
                        bottom_w += 1
                        if is_home:
                            home_bottom_w += 1
                        else:
                            away_bottom_w += 1
                    elif team_goals == opp_goals:
                        bottom_d += 1
                        if is_home:
                            home_bottom_d += 1
                        else:
                            away_bottom_d += 1
                    else:
                        bottom_l += 1
                        if is_home:
                            home_bottom_l += 1
                        else:
                            away_bottom_l += 1

            def pack(w, d, l):
                m_cnt = w + d + l
                return {
                    "matches": m_cnt,
                    "wins": w,
                    "draws": d,
                    "losses": l,
                    "win_rate": (w / m_cnt) if m_cnt else 0.0,
                    "draw_rate": (d / m_cnt) if m_cnt else 0.0,
                    "loss_rate": (l / m_cnt) if m_cnt else 0.0,
                }

            vs_rank_groups = {
                "top_n": top_n,
                "bottom_n": bottom_n,
                "total_teams": total_teams,
                "bottom_threshold_rank": bottom_threshold,

                "vs_top": pack(top_w, top_d, top_l),
                "vs_bottom": pack(bottom_w, bottom_d, bottom_l),

                "home": {
                    "vs_top": pack(home_top_w, home_top_d, home_top_l),
                    "vs_bottom": pack(home_bottom_w, home_bottom_d, home_bottom_l),
                },
                "away": {
                    "vs_top": pack(away_top_w, away_top_d, away_top_l),
                    "vs_bottom": pack(away_bottom_w, away_bottom_d, away_bottom_l),
                },
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

        # Over/Under & BTTS (overall)
        over_25 = under_25 = btts = 0

        # Over/Under & BTTS (home/away split)
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

            # goals
            if m.home_team == team:
                gf, ga = hg, ag
                is_home_game = True
            else:
                gf, ga = ag, hg
                is_home_game = False

            goals_scored += gf
            goals_conceded += ga

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

            # Over/Under 2.5 (overall)
            if (hg + ag) > 2.5:
                over_25 += 1
            else:
                under_25 += 1

            # BTTS (overall)
            if hg > 0 and ag > 0:
                btts += 1

            # split over/under + btts
            if is_home_game:
                if (hg + ag) > 2.5:
                    home_over_25 += 1
                else:
                    home_under_25 += 1
                if hg > 0 and ag > 0:
                    home_btts += 1
            else:
                if (hg + ag) > 2.5:
                    away_over_25 += 1
                else:
                    away_under_25 += 1
                if hg > 0 and ag > 0:
                    away_btts += 1

        # derived overall
        goal_difference = goals_scored - goals_conceded
        avg_scored = goals_scored / matches_played if matches_played else 0.0
        avg_conceded = goals_conceded / matches_played if matches_played else 0.0

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
        def pack_over_under(o, u, b, mp):
            return {
                "over_25": o,
                "under_25": u,
                "btts": b,
                "over_25_rate": (o / mp) if mp else 0.0,
                "under_25_rate": (u / mp) if mp else 0.0,
                "btts_rate": (b / mp) if mp else 0.0,
            }

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

            # rates overall (NEW but safe)
            "win_rate": win_rate,
            "draw_rate": draw_rate,
            "loss_rate": loss_rate,

            # existing rates (kept)
            "home_win_rate": home_win_rate,
            "away_win_rate": away_win_rate,

            # breakdown objects
            "goals": {
                "scored": goals_scored,
                "conceded": goals_conceded,
                "goal_difference": goal_difference,
                "avg_scored": avg_scored,
                "avg_conceded": avg_conceded,
            },

            "over_under": pack_over_under(over_25, under_25, btts, matches_played),

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

                # NEW: advanced split
                "over_under": pack_over_under(home_over_25, home_under_25, home_btts, home_matches),
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

                # NEW: advanced split
                "over_under": pack_over_under(away_over_25, away_under_25, away_btts, away_matches),
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


if __name__ == "__main__":
    app.run(debug=True)
