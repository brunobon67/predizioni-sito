import math
from sqlalchemy import or_

from app.db import SessionLocal
from app.models import Match, MatchContext


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
    W = {
        "rank_pos_weight": 0.50,
        "home_win_weight": 3.0,
        "home_loss_weight": 2.0,
        "away_win_weight": 3.0,
        "away_loss_weight": 2.0,
        "vs_band_weight": 0.8,
        "vs_band_home_weight": 0.4,
        "vs_band_away_weight": 0.4,
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

        home_vs_ppg, home_vs_home_ppg, home_vs_away_ppg, hv_mp, _, _ = _compute_vs_opponent_band_ppg(
            session=session,
            team=home_team,
            competition=competition,
            season=season,
            date_cutoff=date_cutoff,
            opponent_rank_before=away_rank_before,
            total_teams=total_teams,
            band_size=5
        )
        away_vs_ppg, away_vs_home_ppg, away_vs_away_ppg, av_mp, _, _ = _compute_vs_opponent_band_ppg(
            session=session,
            team=away_team,
            competition=competition,
            season=season,
            date_cutoff=date_cutoff,
            opponent_rank_before=home_rank_before,
            total_teams=total_teams,
            band_size=5
        )

        rank_diff = (away_rank_before - home_rank_before)
        rank_score = rank_diff * W["rank_pos_weight"]

        hp = home_stats["home"]
        ap = away_stats["away"]

        home_perf_score = (hp["win_rate"] * W["home_win_weight"]) - (hp["loss_rate"] * W["home_loss_weight"])
        away_perf_score = (ap["win_rate"] * W["away_win_weight"]) - (ap["loss_rate"] * W["away_loss_weight"])

        vs_score = (
            (home_vs_ppg - away_vs_ppg) * W["vs_band_weight"]
            + (home_vs_home_ppg - away_vs_home_ppg) * W["vs_band_home_weight"]
            + (home_vs_away_ppg - away_vs_away_ppg) * W["vs_band_away_weight"]
        )

        gf_diff = (hp["avg_gf"] - ap["avg_gf"])
        ga_diff = (ap["avg_ga"] - hp["avg_ga"])
        goals_score = (gf_diff * W["gf_diff_weight"]) + (ga_diff * W["ga_diff_weight"])

        form_diff = (home_stats["overall"]["last5_ppg"] - away_stats["overall"]["last5_ppg"])
        form_score = form_diff * W["last5_ppg_weight"]

        home_score = rank_score + home_perf_score - away_perf_score + vs_score + goals_score + form_score
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
            "probabilities": {"home_win": p_home, "draw": p_draw, "away_win": p_away},
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
                    "home_vs_band": {"ppg": home_vs_ppg, "home_ppg": home_vs_home_ppg, "away_ppg": home_vs_away_ppg, "mp": hv_mp},
                    "away_vs_band": {"ppg": away_vs_ppg, "home_ppg": away_vs_home_ppg, "away_ppg": away_vs_away_ppg, "mp": av_mp},
                }
            }
        }
    finally:
        session.close()
