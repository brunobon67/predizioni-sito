# backend/app/__init__.py

from flask import Flask
from flask_cors import CORS

from app.db import init_db, db_info
from app.routes.admin import bp_admin
from app.routes.public import bp_public
from app.routes.predict import bp_predict


def create_app():
    """
    Factory che crea e configura l'app Flask.
    Serve come punto centrale di inizializzazione.
    """

    app = Flask(__name__)

    # ---- CORS ----
    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": [
                    "https://predizioni-sito.netlify.app",
                    "http://localhost:5500",
                    "http://127.0.0.1:5500",
                ]
            }
        },
    )

    # ---- Database ----
    init_db()
    db_info()

    # ---- Routes (Blueprint) ----
    app.register_blueprint(bp_admin)
    app.register_blueprint(bp_public)
    app.register_blueprint(bp_predict)

    return app
