# backend/app/routes/predict.py

from flask import Blueprint, request, jsonify
from app.predictors.rules_v1 import predict_rule_based

bp_predict = Blueprint("predict", __name__)


@bp_predict.route("/api/predict", methods=["POST"])
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
