"""Explicit migration for databases with a legacy one-reservation constraint.

The migration accepts an existing SQLAlchemy connection so callers must choose
the target database deliberately. It never opens the application's configured
database on its own.
"""

from sqlalchemy import inspect


def _sqlite_upgrade(connection):
    unique_constraints = inspect(connection).get_unique_constraints(
        "dock_reservations"
    )
    appointment_only = any(
        constraint.get("column_names") == ["appointment_id"]
        for constraint in unique_constraints
    )
    if not appointment_only:
        return False

    connection.exec_driver_sql(
        """
        CREATE TABLE dock_reservations_history (
            id INTEGER NOT NULL PRIMARY KEY,
            dock_id INTEGER NOT NULL REFERENCES docks (id),
            appointment_id INTEGER NOT NULL REFERENCES appointments (id),
            start_at DATETIME NOT NULL,
            end_at DATETIME NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
            CONSTRAINT ck_reservation_time_order CHECK (end_at > start_at),
            CONSTRAINT ck_dock_reservation_status
                CHECK (status IN ('ACTIVE', 'CANCELLED', 'COMPLETED'))
        )
        """
    )
    connection.exec_driver_sql(
        """
        INSERT INTO dock_reservations_history
            (id, dock_id, appointment_id, start_at, end_at, status)
        SELECT id, dock_id, appointment_id, start_at, end_at, status
        FROM dock_reservations
        """
    )
    connection.exec_driver_sql("DROP TABLE dock_reservations")
    connection.exec_driver_sql(
        "ALTER TABLE dock_reservations_history RENAME TO dock_reservations"
    )
    connection.exec_driver_sql(
        "CREATE INDEX ix_dock_reservations_dock_id ON dock_reservations (dock_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX ix_dock_reservations_appointment_id "
        "ON dock_reservations (appointment_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX ix_dock_reservations_start_at ON dock_reservations (start_at)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX ix_dock_reservations_status ON dock_reservations (status)"
    )
    return True


def _mysql_upgrade(connection):
    constraints = inspect(connection).get_unique_constraints("dock_reservations")
    legacy = [
        constraint
        for constraint in constraints
        if constraint.get("column_names") == ["appointment_id"]
    ]
    for constraint in legacy:
        name = constraint.get("name")
        if not name:
            raise RuntimeError(
                "Cannot safely identify the legacy appointment uniqueness index"
            )
        quoted_name = connection.dialect.identifier_preparer.quote(name)
        connection.exec_driver_sql(
            f"ALTER TABLE dock_reservations DROP INDEX {quoted_name}"
        )
    return bool(legacy)


def upgrade(connection):
    """Allow multiple historical reservations per appointment, preserving rows.

    Returns True when a legacy unique constraint was removed. Fresh schemas
    already allow reservation history and return False.
    """
    if not inspect(connection).has_table("dock_reservations"):
        raise RuntimeError("dock_reservations table does not exist")
    if connection.dialect.name == "sqlite":
        return _sqlite_upgrade(connection)
    if connection.dialect.name == "mysql":
        return _mysql_upgrade(connection)
    raise NotImplementedError(
        f"Reservation history migration is not implemented for "
        f"{connection.dialect.name}"
    )
