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
        q = session.query(Match).filter(Match.status == "FINISHED")

        if competition:
            q = q.filter(Match.competition == competition)
        if season is not None:
            q = q.filter(Match.season == season)

        teams = set()
        for m in q.all():
            if m.home_team:
                teams.add(m.home_team)
            if m.away_team:
                teams.add(m.away_team)

        return jsonify({"teams": sorted(list(teams))})
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
                "season": m.season,
                "date": m.date.isoformat() if m.date else None,
                "status": m.status,
                "home_team": m.home_team,
                "away_team": m.away_team,
            }
            for m in matches
        ]

        return jsonify({"matches": results})
    finally:
        session.close()


@bp_public.route("/api/stats", methods=["GET"])
def get_stats():
    """
    Stats endpoint used by the Netlify frontend.

    Query params:
      - team (required)
      - competition (optional)
      - season (optional, int)

    Response format is aligned to frontend/script.js renderStats().
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
        matches = q.order_by(Match.date.asc(), Match.id.asc()).all()

        # Helper accumulators
        def empty_bucket():
            return {
                "matches": 0,
                "wins": 0,
                "draws": 0,
                "losses": 0,
                "goals_scored": 0,
                "goals_conceded": 0,
                "failed_to_score": 0,
                "tot_goals": 0,  # scored + conceded per match (sum)
                "ou": {  # counts
                    0.5: {"over": 0, "under": 0},
                    1.5: {"over": 0, "under": 0},
                    2.5: {"over": 0, "under": 0},
                    3.5: {"over": 0, "under": 0},
                    4.5: {"over": 0, "under": 0},
                },
                "btts": 0,
                "last": [],  # list of (result_char, gf, ga)
            }

        def push_match(bucket, gf, ga, result_char):
            bucket["matches"] += 1
            bucket["goals_scored"] += gf
            bucket["goals_conceded"] += ga
            bucket["tot_goals"] += (gf + ga)
            if gf == 0:
                bucket["failed_to_score"] += 1

            if result_char == "W":
                bucket["wins"] += 1
            elif result_char == "D":
                bucket["draws"] += 1
            else:
                bucket["losses"] += 1

            total = gf + ga
            for line in (0.5, 1.5, 2.5, 3.5, 4.5):
                if total > line:
                    bucket["ou"][line]["over"] += 1
                else:
                    bucket["ou"][line]["under"] += 1

            if gf > 0 and ga > 0:
                bucket["btts"] += 1

            bucket["last"].append((result_char, gf, ga))

        overall = empty_bucket()
        home_b = empty_bucket()
        away_b = empty_bucket()

        match_ids = []
        for m in matches:
            hg = m.home_goals or 0
            ag = m.away_goals or 0
            is_home = (m.home_team == team)

            gf = hg if is_home else ag
            ga = ag if is_home else hg

            if gf > ga:
                res = "W"
            elif gf < ga:
                res = "L"
            else:
                res = "D"

            push_match(overall, gf, ga, res)
            if is_home:
                push_match(home_b, gf, ga, res)
            else:
                push_match(away_b, gf, ga, res)

            match_ids.append(m.id)

        def summarize(bucket):
            mp = bucket["matches"]
            wins = bucket["wins"]
            draws = bucket["draws"]
            losses = bucket["losses"]
            gf = bucket["goals_scored"]
            ga = bucket["goals_conceded"]
            pts = wins * 3 + draws

            win_rate = (wins / mp) if mp else 0.0
            draw_rate = (draws / mp) if mp else 0.0
            loss_rate = (losses / mp) if mp else 0.0

            avg_scored = (gf / mp) if mp else 0.0
            avg_conceded = (ga / mp) if mp else 0.0
            avg_total_goals = (bucket["tot_goals"] / mp) if mp else 0.0

            # Over/Under lines
            lines = {}
            for line in (0.5, 1.5, 2.5, 3.5, 4.5):
                over = bucket["ou"][line]["over"]
                under = bucket["ou"][line]["under"]
                lines[str(line).replace(".", "_")] = {
                    "line": line,
                    "over": over,
                    "under": under,
                    "over_rate": (over / mp) if mp else 0.0,
                    "under_rate": (under / mp) if mp else 0.0,
                }

            ou = {
                "over_25": bucket["ou"][2.5]["over"],
                "under_25": bucket["ou"][2.5]["under"],
                "btts": bucket["btts"],
                "over_25_rate": (bucket["ou"][2.5]["over"] / mp) if mp else 0.0,
                "under_25_rate": (bucket["ou"][2.5]["under"] / mp) if mp else 0.0,
                "btts_rate": (bucket["btts"] / mp) if mp else 0.0,
                "lines": lines,
            }

            fts = {
                "count": bucket["failed_to_score"],
                "rate": (bucket["failed_to_score"] / mp) if mp else 0.0,
            }

            # Form: last 5/10 (from bucket["last"])
            def form_block(n):
                last_n = bucket["last"][-n:] if n > 0 else []
                w = sum(1 for r, _, __ in last_n if r == "W")
                d = sum(1 for r, _, __ in last_n if r == "D")
                l = sum(1 for r, _, __ in last_n if r == "L")
                pts_n = w * 3 + d
                gf_n = sum(gf1 for _, gf1, __ in last_n)
                ga_n = sum(ga1 for _, __, ga1 in last_n)
                return {
                    "matches": len(last_n),
                    "record": f"{w}W-{d}D-{l}L",
                    "points": pts_n,
                    "goals_scored": gf_n,
                    "goals_conceded": ga_n,
                }

            form = {
                "last_5": form_block(5),
                "last_10": form_block(10),
            }

            return {
                "matches": mp,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "win_rate": win_rate,
                "draw_rate": draw_rate,
                "loss_rate": loss_rate,
                "goals_scored": gf,
                "goals_conceded": ga,
                "avg_scored": avg_scored,
                "avg_conceded": avg_conceded,
                "avg_total_goals": avg_total_goals,
                "points": pts,
                "ppg": (pts / mp) if mp else 0.0,
                "over_under": ou,
                "failed_to_score": fts,
                "form": form,
            }

        # Build vs-rank groups using MatchContext (only if comp+season are provided)
        vsg = None
        if competition and (season_param is not None) and match_ids:
            ctx_rows = (
                session.query(MatchContext)
                .filter(MatchContext.competition == competition)
                .filter(MatchContext.season == season_param)
                .filter(MatchContext.match_id.in_(match_ids))
                .all()
            )

            if ctx_rows:
                total_teams = max((c.total_teams or 0) for c in ctx_rows) or 0
                top_n = 6 if total_teams >= 18 else (max(3, total_teams // 3) if total_teams else 6)
                bottom_n = 5 if total_teams >= 18 else (max(3, total_teams // 4) if total_teams else 5)
                bottom_threshold_rank = max(1, total_teams - bottom_n + 1) if total_teams else None

                def empty_group():
                    return {"matches": 0, "wins": 0, "draws": 0, "losses": 0, "goals_for": 0, "goals_against": 0}

                groups_overall = {"Top": empty_group(), "Mid": empty_group(), "Bottom": empty_group()}
                groups_home = {"Top": empty_group(), "Mid": empty_group(), "Bottom": empty_group()}
                groups_away = {"Top": empty_group(), "Mid": empty_group(), "Bottom": empty_group()}

                match_map = {m.id: m for m in matches}

                for c in ctx_rows:
                    m = match_map.get(c.match_id)
                    if not m:
                        continue

                    is_home = (m.home_team == team)
                    hg = m.home_goals or 0
                    ag = m.away_goals or 0
                    gf = hg if is_home else ag
                    ga = ag if is_home else hg

                    if gf > ga:
                        res = "W"
                    elif gf < ga:
                        res = "L"
                    else:
                        res = "D"

                    opp_rank = c.away_rank_before if is_home else c.home_rank_before
                    if not opp_rank:
                        band = "Mid"
                    elif opp_rank <= top_n:
                        band = "Top"
                    elif bottom_threshold_rank and opp_rank >= bottom_threshold_rank:
                        band = "Bottom"
                    else:
                        band = "Mid"

                    for target in (groups_overall, (groups_home if is_home else groups_away)):
                        g = target[band]
                        g["matches"] += 1
                        g["goals_for"] += gf
                        g["goals_against"] += ga
                        if res == "W":
                            g["wins"] += 1
                        elif res == "D":
                            g["draws"] += 1
                        else:
                            g["losses"] += 1

                def finalize_group(g):
                    mp = g["matches"]
                    pts = g["wins"] * 3 + g["draws"]
                    return {
                        "matches": mp,
                        "wins": g["wins"],
                        "draws": g["draws"],
                        "losses": g["losses"],
                        "win_rate": (g["wins"] / mp) if mp else 0.0,
                        "ppg": (pts / mp) if mp else 0.0,
                        "goals_for": g["goals_for"],
                        "goals_against": g["goals_against"],
                    }

                bands = ["Top", "Mid", "Bottom"]
                vsg = {
                    "competition": competition,
                    "season": season_param,
                    "total_teams": total_teams,
                    "top_n": top_n,
                    "bottom_n": bottom_n,
                    "bottom_threshold_rank": bottom_threshold_rank,
                    "rank_bands": bands,
                    "bands": {b: finalize_group(groups_overall[b]) for b in bands},
                    "bands_home": {b: finalize_group(groups_home[b]) for b in bands},
                    "bands_away": {b: finalize_group(groups_away[b]) for b in bands},
                    "vs_top": finalize_group(groups_overall["Top"]),
                    "vs_mid": finalize_group(groups_overall["Mid"]),
                    "vs_bottom": finalize_group(groups_overall["Bottom"]),
                    "home": {
                        "vs_top": finalize_group(groups_home["Top"]),
                        "vs_mid": finalize_group(groups_home["Mid"]),
                        "vs_bottom": finalize_group(groups_home["Bottom"]),
                    },
                    "away": {
                        "vs_top": finalize_group(groups_away["Top"]),
                        "vs_mid": finalize_group(groups_away["Mid"]),
                        "vs_bottom": finalize_group(groups_away["Bottom"]),
                    },
                }

        overall_s = summarize(overall)
        home_s = summarize(home_b)
        away_s = summarize(away_b)

        mp = overall_s["matches"]
        out = {
            "team": team,
            "competition": competition or "All",
            "season": season_param if season_param is not None else "All",

            "matches_played": mp,
            "wins": overall_s["wins"],
            "draws": overall_s["draws"],
            "losses": overall_s["losses"],
            "win_rate": overall_s["win_rate"],
            "draw_rate": overall_s["draw_rate"],
            "loss_rate": overall_s["loss_rate"],

            "goals_scored": overall_s["goals_scored"],
            "goals_conceded": overall_s["goals_conceded"],
            "goals": {
                "avg_scored": overall_s["avg_scored"],
                "avg_conceded": overall_s["avg_conceded"],
                "avg_total_goals": overall_s["avg_total_goals"],
                "goal_difference": overall_s["goals_scored"] - overall_s["goals_conceded"],
            },

            "over_under": overall_s["over_under"],
            "failed_to_score": overall_s["failed_to_score"],
            "form": overall_s["form"],

            "home": home_s,
            "away": away_s,

            "vs_rank_groups": vsg or {"note": "MatchContext non disponibile (serve competition + season + rebuild context)"},
        }

        return jsonify(out)
    finally:
        session.close()


@bp_public.route("/api/standings", methods=["GET"])
def standings_snapshot():
    competition = request.args.get("competition")
    season = request.args.get("season", type=int)
    date_limit = request.args.get("date")  # YYYY-MM-DD

    if not competition or season is None or not date_limit:
        return jsonify({"error": "Servono competition, season, date"}), 400

    session = SessionLocal()
    try:
        matches = (
            session.query(Match)
            .filter(Match.status == "FINISHED")
            .filter(Match.competition == competition)
            .filter(Match.season == season)
            .filter(Match.date <= date_limit)
            .order_by(Match.date.asc(), Match.id.asc())
            .all()
        )

        table = {}

        def ensure(team):
            if team not in table:
                table[team] = {
                    "team": team,
                    "played": 0,
                    "wins": 0,
                    "draws": 0,
                    "losses": 0,
                    "gf": 0,
                    "ga": 0,
                    "points": 0,
                }

        for m in matches:
            home = m.home_team
            away = m.away_team
            if not home or not away:
                continue

            ensure(home)
            ensure(away)

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
                table[away]["losses"] += 1
                table[home]["points"] += 3
            elif hg < ag:
                table[away]["wins"] += 1
                table[home]["losses"] += 1
                table[away]["points"] += 3
            else:
                table[home]["draws"] += 1
                table[away]["draws"] += 1
                table[home]["points"] += 1
                table[away]["points"] += 1

        rows = list(table.values())
        for r in rows:
            r["gd"] = r["gf"] - r["ga"]

        rows.sort(
            key=lambda r: (r["points"], r["gd"], r["gf"], r["played"], r["team"]),
            reverse=True,
        )
        for i, r in enumerate(rows, start=1):
            r["rank"] = i

        return jsonify({"competition": competition, "season": season, "date": date_limit, "standings": rows})
    finally:
        session.close()
