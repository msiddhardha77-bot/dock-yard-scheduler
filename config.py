import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'dockyard.db'}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Works for both MySQL/PyMySQL and SQLite.  The URL is intentionally the
    # only place a local password may be supplied.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    ITEMS_PER_PAGE = int(os.getenv("ITEMS_PER_PAGE", "25"))
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "UTC")


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


def database_dialect(uri=None):
    """Return a non-secret database dialect label for diagnostics."""
    uri = uri or Config.SQLALCHEMY_DATABASE_URI
    return uri.split(":", 1)[0].split("+", 1)[0]
