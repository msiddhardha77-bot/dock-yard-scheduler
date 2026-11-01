from flask import Flask, jsonify
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from config import Config, database_dialect

db = SQLAlchemy()
migrate = Migrate()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    db.init_app(app)
    migrate.init_app(app, db)

    from app.models import masters, operations, scheduling, events  # noqa: F401
    from app.routes.dashboard import dashboard_bp
    from app.routes.appointments import appointments_bp
    from app.routes.checkins import checkins_bp
    from app.routes.exceptions import exceptions_bp
    from app.routes.reports import reports_bp
    from app.routes.masters import masters_bp
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(appointments_bp, url_prefix="/appointments")
    app.register_blueprint(checkins_bp, url_prefix="/checkins")
    app.register_blueprint(exceptions_bp, url_prefix="/exceptions")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(masters_bp, url_prefix="/masters")

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "dock-yard-scheduler", "database_dialect": database_dialect(app.config["SQLALCHEMY_DATABASE_URI"])})

    @app.get("/health/db")
    def database_health():
        """Safe connectivity probe; never returns the configured URL/password."""
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify({"status": "ok", "database": "reachable", "dialect": db.engine.dialect.name})
        except SQLAlchemyError:
            db.session.rollback()
            return jsonify({"status": "error", "database": "unreachable", "dialect": db.engine.dialect.name}), 503

    @app.cli.command("init-db")
    def init_db():
        db.create_all()
        print("Database tables created.")

    return app
