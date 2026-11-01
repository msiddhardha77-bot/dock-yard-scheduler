"""Opt-in MySQL 8 tests.

These tests intentionally require MYSQL_TEST_DATABASE_URL rather than the
application DATABASE_URL, so they cannot mutate the normal development DB by
accident. Set it only to a dedicated disposable test database.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone, time
import time as time_module

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from app import create_app, db
from app.models.masters import Carrier, Dock, Facility, LaborShift, Vehicle
from app.models.operations import Appointment, Shipment
from app.models.domain import YardSlot
from app.models.scheduling import DockReservation, SchedulingDecision
from app.services.scheduler import schedule_appointment


MYSQL_URL = os.getenv("MYSQL_TEST_DATABASE_URL", "")
MYSQL_DATABASE_NAME = make_url(MYSQL_URL).database if MYSQL_URL.startswith("mysql+pymysql://") else None
pytestmark = pytest.mark.skipif(
    not MYSQL_URL.startswith("mysql+pymysql://") or MYSQL_DATABASE_NAME != "dock_yard_scheduler_test",
    reason="MYSQL_TEST_DATABASE_URL must target the dedicated dock_yard_scheduler_test database",
)


class MySQLTestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = MYSQL_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}


@pytest.fixture(scope="module")
def mysql_app():
    app = create_app(MySQLTestConfig)
    with app.app_context():
        db.create_all()
        yield app


def test_mysql_connectivity_and_schema(mysql_app):
    with mysql_app.app_context():
        assert db.engine.dialect.name == "mysql"
        assert db.session.execute(text("SELECT 1")).scalar() == 1
        tables = set(inspect(db.engine).get_table_names())
        assert "appointments" in tables
        assert "dock_reservations" in tables


def test_mysql_competing_bookings_are_serialized(mysql_app):
    """Two MySQL sessions compete for one dock; at most one may schedule."""
    with mysql_app.app_context():
        suffix = str(int(time_module.time() * 1000000))[-10:]
        facility = Facility(code=f"MYSQL-{suffix}", name="MySQL concurrency")
        carrier = Carrier(code=f"MYSQL-C-{suffix}", name="MySQL carrier")
        db.session.add_all([facility, carrier]); db.session.flush()
        db.session.add_all([Dock(facility_id=facility.id, code="DOCK-001"), LaborShift(facility_id=facility.id, name="day", start_time=time(0), end_time=time(23, 59), workers=5), YardSlot(facility_id=facility.id, code="YARD-001", capacity=5)])
        vehicle = Vehicle(carrier_id=carrier.id, registration=f"MYSQL-V-{suffix}", vehicle_type="TRUCK")
        db.session.add(vehicle); db.session.flush()
        start = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(hours=1)
        appointments = []
        for index in (1, 2):
            shipment = Shipment(reference=f"MYSQL-S-{suffix}-{index}", facility_id=facility.id, carrier_id=carrier.id, vehicle_id=vehicle.id, direction="INBOUND", weight_kg=100)
            db.session.add(shipment); db.session.flush()
            appointment = Appointment(reference=f"MYSQL-A-{suffix}-{index}", shipment_id=shipment.id, facility_id=facility.id, requested_start=start, requested_end=start + timedelta(hours=2))
            db.session.add(appointment); db.session.flush(); appointments.append(appointment.id)
        db.session.commit()

    def book(appointment_id):
        with mysql_app.app_context():
            appointment = db.session.get(Appointment, appointment_id)
            reservation = schedule_appointment(appointment)
            return {"appointment_id": appointment_id, "returned": reservation is not None,
                    "dock_id": reservation.dock_id if reservation else None}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(book, appointments))
    with mysql_app.app_context():
        persisted = [db.session.get(Appointment, item["appointment_id"]) for item in results]
        active = [DockReservation.query.filter_by(appointment_id=item["appointment_id"], status="ACTIVE").one_or_none() for item in results]
        decisions = [SchedulingDecision.query.filter_by(appointment_id=item["appointment_id"]).order_by(SchedulingDecision.id.desc()).first() for item in results]
        assert sum(item.status == "SCHEDULED" for item in persisted) == 1
        assert sum(item is not None for item in active) == 1
        assert sum(item.decision == "ACCEPTED" for item in decisions) == 1
        assert sum(item.decision == "REJECTED" for item in decisions) == 1
        assert sum(item["returned"] for item in results) == 1


def test_mysql_non_overlapping_bookings_both_succeed(mysql_app):
    with mysql_app.app_context():
        suffix = str(int(time_module.time() * 1000000))[-10:]
        facility = Facility(code=f"MYSQL-N-{suffix}", name="MySQL non-overlap")
        carrier = Carrier(code=f"MYSQL-NC-{suffix}", name="MySQL carrier")
        db.session.add_all([facility, carrier]); db.session.flush()
        db.session.add_all([Dock(facility_id=facility.id, code="DOCK-001"), LaborShift(facility_id=facility.id, name="day", start_time=time(0), end_time=time(23, 59), workers=5), YardSlot(facility_id=facility.id, code="YARD-001", capacity=5)])
        vehicle = Vehicle(carrier_id=carrier.id, registration=f"MYSQL-NV-{suffix}", vehicle_type="TRUCK")
        db.session.add(vehicle); db.session.flush()
        start = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(hours=1)
        ids = []
        for index, offset in enumerate((0, 2), 1):
            shipment = Shipment(reference=f"MYSQL-NS-{suffix}-{index}", facility_id=facility.id, carrier_id=carrier.id, vehicle_id=vehicle.id, direction="INBOUND", weight_kg=100)
            db.session.add(shipment); db.session.flush()
            appointment = Appointment(reference=f"MYSQL-NA-{suffix}-{index}", shipment_id=shipment.id, facility_id=facility.id, requested_start=start + timedelta(hours=offset), requested_end=start + timedelta(hours=offset + 2))
            db.session.add(appointment); db.session.flush(); ids.append(appointment.id)
        db.session.commit()
    def book(appointment_id):
        with mysql_app.app_context():
            appointment = db.session.get(Appointment, appointment_id)
            reservation = schedule_appointment(appointment)
            return appointment_id, reservation is not None, reservation.dock_id if reservation else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(book, ids))

    with mysql_app.app_context():
        persisted = [db.session.get(Appointment, appointment_id) for appointment_id in ids]
        reservations = [DockReservation.query.filter_by(appointment_id=appointment_id, status="ACTIVE").one_or_none()
                        for appointment_id in ids]
        assert all(item[1] for item in results)
        assert all(appointment.status == "SCHEDULED" for appointment in persisted)
        assert all(reservation is not None for reservation in reservations)
        assert reservations[0].dock_id == reservations[1].dock_id
        assert reservations[0].end_at <= reservations[1].start_at
