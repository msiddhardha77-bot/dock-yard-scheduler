from sqlalchemy import create_engine, inspect, text

from app import db
from database.migrations.dock_reservation_history import upgrade


def _legacy_database(path):
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql(
            "CREATE TABLE facilities (id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE docks (id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL "
            "REFERENCES facilities(id))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE carriers (id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE vehicles (id INTEGER PRIMARY KEY, carrier_id INTEGER "
            "NOT NULL REFERENCES carriers(id))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE shipments (id INTEGER PRIMARY KEY, facility_id INTEGER "
            "NOT NULL REFERENCES facilities(id), carrier_id INTEGER NOT NULL "
            "REFERENCES carriers(id), vehicle_id INTEGER NOT NULL REFERENCES vehicles(id))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE appointments (id INTEGER PRIMARY KEY, shipment_id INTEGER "
            "NOT NULL REFERENCES shipments(id))"
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE dock_reservations (
                id INTEGER PRIMARY KEY,
                dock_id INTEGER NOT NULL REFERENCES docks(id),
                appointment_id INTEGER NOT NULL UNIQUE REFERENCES appointments(id),
                start_at DATETIME NOT NULL,
                end_at DATETIME NOT NULL,
                status VARCHAR(20) NOT NULL
            )
            """
        )
        connection.exec_driver_sql("INSERT INTO facilities VALUES (1)")
        connection.exec_driver_sql("INSERT INTO docks VALUES (1, 1)")
        connection.exec_driver_sql("INSERT INTO carriers VALUES (1)")
        connection.exec_driver_sql("INSERT INTO vehicles VALUES (1, 1)")
        connection.exec_driver_sql("INSERT INTO shipments VALUES (1, 1, 1, 1)")
        connection.exec_driver_sql("INSERT INTO appointments VALUES (1, 1)")
        connection.exec_driver_sql(
            "INSERT INTO dock_reservations VALUES "
            "(7, 1, 1, '2026-01-01 10:00:00', '2026-01-01 11:00:00', 'CANCELLED')"
        )
    return engine


def test_legacy_migration_preserves_rows_and_allows_reservation_history(tmp_path):
    engine = _legacy_database(tmp_path / "legacy.sqlite")
    try:
        with engine.begin() as connection:
            assert upgrade(connection) is True
            assert connection.execute(
                text("PRAGMA foreign_key_check")
            ).all() == []
            assert connection.execute(
                text(
                    "SELECT id, appointment_id, status FROM dock_reservations"
                )
            ).all() == [(7, 1, "CANCELLED")]
            connection.execute(
                text(
                    "INSERT INTO dock_reservations "
                    "(id, dock_id, appointment_id, start_at, end_at, status) "
                    "VALUES (8, 1, 1, '2026-01-01 11:00:00', "
                    "'2026-01-01 12:00:00', 'ACTIVE')"
                )
            )
        unique_constraints = inspect(engine).get_unique_constraints(
            "dock_reservations"
        )
        assert not any(
            constraint["column_names"] == ["appointment_id"]
            for constraint in unique_constraints
        )
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT COUNT(*) FROM dock_reservations WHERE appointment_id=1")
            ).scalar_one() == 2
    finally:
        engine.dispose()


def test_fresh_reservation_schema_does_not_need_migration(app):
    with app.app_context():
        with db.engine.begin() as connection:
            assert upgrade(connection) is False
        unique_constraints = inspect(db.engine).get_unique_constraints(
            "dock_reservations"
        )
        assert not any(
            constraint["column_names"] == ["appointment_id"]
            for constraint in unique_constraints
        )
