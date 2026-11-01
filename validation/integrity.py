from sqlalchemy import text


def foreign_key_check(session):
    """Run SQLite's FK check where supported; MySQL enforces FK constraints natively."""
    if session.get_bind().dialect.name != "sqlite":
        return []
    return list(session.execute(text("PRAGMA foreign_key_check")))
