import hashlib
import json
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text

from app import create_app, db
from app.models.domain import (
    AppointmentTimeline,
    CheckInEvent,
    HandlingRequirement,
    YardSlot,
    YardSlotReservation,
)
from app.models.events import (
    AnomalyLabel,
    GroundTruthRecord,
    LifecycleEvent,
    OperationalException,
)
from app.models.masters import (
    Carrier,
    Dock,
    Facility,
    LaborAssignment,
    LaborShift,
    Vehicle,
)
from app.models.operations import Appointment, Shipment
from app.models.scheduling import DockReservation, SchedulingDecision
from app.services.lifecycle import TRANSITIONS, allowed_transition
from app.services.metrics import (
    appointment_status_counts,
    dashboard_metrics,
    dock_utilization_metrics,
    evaluation_metrics,
    timeline_metrics,
)
from app.services.scheduler import schedule_appointment
from app.services.compatibility import (
    handles_requirement,
    handling_yard_slot_type,
)
from config import Config
from database.migrations.dock_reservation_history import upgrade
from generator.generate import _allocate_facility_appointments, generate
from generator.settings import FACILITY_APPOINTMENT_WEIGHTS, FULL
from validation.capacities import resource_capacity_summary
from validation.reconciliation import reconcile
from validation.scenario_evaluator import evaluate
from validation.validate import validation_summary


@pytest.fixture
def temporary_app(tmp_path):
    database_path = tmp_path / "integration.sqlite"
    config = type(
        "TemporaryIntegrationConfig",
        (Config,),
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
        },
    )
    app = create_app(config)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def _generator_app(database_path):
    config = type(
        "TemporaryGeneratorReadConfig",
        (Config,),
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
        },
    )
    return create_app(config)


def _database_snapshot(database_path):
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        inspector = inspect(engine)
        metadata = MetaData()
        snapshot = {}
        with engine.connect() as connection:
            for table_name in sorted(
                name
                for name in inspector.get_table_names()
                if not name.startswith("sqlite_")
            ):
                table = Table(
                    table_name,
                    metadata,
                    autoload_with=connection,
                )
                primary_keys = inspector.get_pk_constraint(table_name)[
                    "constrained_columns"
                ]
                order_columns = primary_keys or list(table.columns.keys())
                rows = connection.execute(
                    select(table).order_by(
                        *(table.c[name] for name in order_columns)
                    )
                ).all()
                snapshot[table_name] = {
                    "columns": list(table.columns.keys()),
                    "rows": [list(row) for row in rows],
                }
        counts = {
            name: len(table["rows"])
            for name, table in snapshot.items()
        }
        encoded = json.dumps(
            snapshot,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return counts, hashlib.sha256(encoded).hexdigest()
    finally:
        engine.dispose()


def test_temporary_schema_and_fresh_migration_cover_required_entities(
    temporary_app,
):
    required_models = (
        Facility,
        Dock,
        YardSlot,
        Carrier,
        Vehicle,
        Appointment,
        Shipment,
        LaborShift,
        HandlingRequirement,
        CheckInEvent,
        DockReservation,
        YardSlotReservation,
        AppointmentTimeline,
        LifecycleEvent,
    )
    expected_tables = {model.__tablename__ for model in required_models}

    with temporary_app.app_context():
        with db.engine.begin() as connection:
            assert upgrade(connection) is False
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert dock_utilization_metrics()["dock_utilization"] is None

        schema = inspect(db.engine)
        assert expected_tables <= set(schema.get_table_names())
        for model in required_models:
            table_name = model.__tablename__
            assert schema.get_pk_constraint(table_name)["constrained_columns"]
            for foreign_key in schema.get_foreign_keys(table_name):
                assert foreign_key["referred_table"] in schema.get_table_names()

        assert {"docks", "yard_slots", "labor_shifts"} <= set(
            inspect(Facility).relationships.keys()
        )
        assert {
            "shipment",
            "dock_reservations",
            "yard_slot_reservations",
            "check_in_events",
            "timeline",
            "events",
        } <= set(inspect(Appointment).relationships.keys())
        assert "reservations" in inspect(YardSlot).relationships
        assert "handling_requirement" in inspect(Shipment).relationships

        expected_states = {
            "REQUESTED",
            "SCHEDULED",
            "CHECKED_IN",
            "AT_DOCK",
            "IN_SERVICE",
            "COMPLETED",
            "DEPARTED",
            "CANCELLED",
            "REJECTED",
            "NO_SHOW",
        }
        assert set(TRANSITIONS) == expected_states
        assert allowed_transition("REQUESTED", "SCHEDULED")
        assert not allowed_transition("REQUESTED", "DEPARTED")


def test_full_mode_facility_plan_fits_the_60_day_horizon():
    counts = _allocate_facility_appointments(
        FULL["appointments"],
        FACILITY_APPOINTMENT_WEIGHTS,
    )
    assert len(counts) == FULL["facilities"]
    assert sum(counts) == FULL["appointments"] == 20000
    assert max(counts) <= 40 * 60
    assert FULL["appointments"] * 5 == 100000


def test_scheduling_integrates_multiple_facilities_and_resources(temporary_app):
    appointment_start = datetime(2026, 10, 15, 10, tzinfo=timezone.utc)
    with temporary_app.app_context():
        facilities = [
            Facility(code="SITE-A", name="Facility A", yard_capacity=10),
            Facility(code="SITE-B", name="Facility B", yard_capacity=5),
        ]
        carriers = [
            Carrier(code=f"CARRIER-{number}", name=f"Carrier {number}")
            for number in range(1, 5)
        ]
        db.session.add_all(facilities + carriers)
        db.session.flush()

        for index, facility in enumerate(facilities):
            dock_count = 2 if index == 0 else 1
            slot_count = 3 if index == 0 else 1
            db.session.add_all(
                [
                    Dock(
                        facility_id=facility.id,
                        code=f"{facility.code}-DOCK-{number}",
                    )
                    for number in range(1, dock_count + 1)
                ]
            )
            db.session.add_all(
                [
                    YardSlot(
                        facility_id=facility.id,
                        code=f"{facility.code}-YARD-{number}",
                        capacity=1,
                    )
                    for number in range(1, slot_count + 1)
                ]
            )
            db.session.add(
                LaborShift(
                    facility_id=facility.id,
                    name=f"{facility.code} day",
                    start_time=time(6),
                    end_time=time(22),
                    workers=4,
                )
            )

        vehicles = [
            Vehicle(
                carrier_id=carrier.id,
                registration=f"VEHICLE-{index}",
                vehicle_type="TRUCK",
                capacity_kg=20000,
            )
            for index, carrier in enumerate(carriers, 1)
        ]
        db.session.add_all(vehicles)
        db.session.flush()

        appointment_specs = (
            (facilities[0], 0, "A-1"),
            (facilities[0], 1, "A-2"),
            (facilities[0], 2, "A-3"),
            (facilities[1], 3, "B-1"),
        )
        appointments = []
        for facility, resource_index, code in appointment_specs:
            shipment = Shipment(
                reference=f"SHIP-{code}",
                facility_id=facility.id,
                carrier_id=carriers[resource_index].id,
                vehicle_id=vehicles[resource_index].id,
                direction="INBOUND",
                weight_kg=1000,
            )
            db.session.add(shipment)
            db.session.flush()
            appointment = Appointment(
                reference=f"APPT-{code}",
                shipment_id=shipment.id,
                facility_id=facility.id,
                requested_start=appointment_start,
                requested_end=appointment_start + timedelta(hours=2),
                duration_minutes=60,
            )
            db.session.add(appointment)
            appointments.append(appointment)
        db.session.commit()

        results = [
            schedule_appointment(appointment)
            for appointment in appointments
        ]
        db.session.expire_all()

        assert [appointment.status for appointment in appointments] == [
            "SCHEDULED",
            "SCHEDULED",
            "REJECTED",
            "SCHEDULED",
        ]
        assert all(result is not None for result in (results[0], results[1], results[3]))
        assert results[2] is None
        rejection = SchedulingDecision.query.filter_by(
            appointment_id=appointments[2].id,
            decision="REJECTED",
        ).one()
        assert rejection.reason_code == "DOCK_UNAVAILABLE"
        assert DockReservation.query.filter_by(status="ACTIVE").count() == 3
        assert YardSlotReservation.query.filter_by(status="ACTIVE").count() == 3
        assert LaborAssignment.query.count() == 3
        assert len(
            {
                row.dock_id
                for row in DockReservation.query.filter(
                    DockReservation.appointment_id.in_(
                        [appointments[0].id, appointments[1].id]
                    ),
                    DockReservation.status == "ACTIVE",
                )
            }
        ) == 2
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []


def test_all_negative_scenarios_execute_against_temporary_database(tmp_path):
    database_path = tmp_path / "scenarios.sqlite"
    result = evaluate(f"sqlite:///{database_path.as_posix()}")

    assert len(result) == 5
    assert all(row["pass"] for row in result)
    assert {
        row["issue_type"] for row in result
    } == {
        "DOCK_CAPACITY_EXCEEDED",
        "INCOMPATIBLE_LOAD_ASSIGNMENT",
        "CHECK_IN_BEFORE_APPOINTMENT_DATE",
        "LABOR_UNAVAILABLE",
        "NO_SHOW_NOT_RECORDED",
    }


def test_starter_generation_is_reproducible_across_temporary_databases(
    tmp_path,
):
    first_path = tmp_path / "first.sqlite"
    second_path = tmp_path / "second.sqlite"
    first_result = generate(
        seed=20261022,
        mode="starter",
        database_url=f"sqlite:///{first_path.as_posix()}",
    )
    second_result = generate(
        seed=20261022,
        mode="starter",
        database_url=f"sqlite:///{second_path.as_posix()}",
    )

    first_counts, first_checksum = _database_snapshot(first_path)
    second_counts, second_checksum = _database_snapshot(second_path)
    assert first_result == second_result
    assert first_result["appointments"] == 40
    assert first_result["events"] == 80
    assert first_result["carriers"] == 20
    assert first_result["vehicles"] == 60
    assert first_result["refrigerated_shipments"] == 4
    assert first_result["hazardous_shipments"] == 2
    assert set(first_result["anomaly_distribution"]) == {
        "BASELINE",
        "CHECK_IN_BEFORE_APPOINTMENT_DATE",
        "DOCK_CAPACITY_EXCEEDED",
        "INCOMPATIBLE_LOAD_ASSIGNMENT",
        "LABOR_UNAVAILABLE",
        "NO_SHOW_NOT_RECORDED",
    }
    assert first_result["anomaly_distribution"]["BASELINE"] == 35
    assert first_result["exception_distribution"] == {}
    assert first_counts == second_counts
    assert first_checksum == second_checksum

    for database_path in (first_path, second_path):
        app = _generator_app(database_path)
        with app.app_context():
            summary = validation_summary(db.session)
            assert summary["foreign_key_integrity"] is True
            assert summary["lifecycle_histories_valid"] is True
            assert summary["timeline_ordering"] is True
            assert summary["ground_truth_label_consistency"] is True
            assert AnomalyLabel.query.count() == 40
            assert GroundTruthRecord.query.count() == 40
            assert CheckInEvent.query.filter_by(
                reason_code="EARLY_CHECK_IN"
            ).count() == 1
            assert HandlingRequirement.query.count() == 40
            assert (
                YardSlotReservation.query.count()
                == first_result["scheduled_appointments"]
            )


def test_medium_generator_distributes_and_validates_parent_records(tmp_path):
    database_path = tmp_path / "medium.sqlite"
    result = generate(
        seed=20261022,
        mode="medium",
        database_url=f"sqlite:///{database_path.as_posix()}",
    )

    assert result["facilities"] == 10
    assert result["docks"] == 100
    assert result["appointments"] == 1000
    assert result["carriers"] == 20
    assert result["vehicles"] == 60
    assert result["yard_slots"] == 100
    assert result["labor_shifts"] == 21
    assert result["events"] == 2000
    assert sum(result["facility_appointment_distribution"].values()) == 1000
    assert len(result["facility_appointment_distribution"]) == 10
    assert min(result["facility_appointment_distribution"].values()) >= 70
    assert max(result["facility_appointment_distribution"].values()) <= 140
    assert sum(result["carrier_appointment_distribution"].values()) == 1000
    assert min(result["carrier_appointment_distribution"].values()) > 0
    assert sum(result["vehicle_type_distribution"].values()) == 1000
    assert set(result["vehicle_type_distribution"]) == {
        "VAN",
        "TRUCK",
        "TRAILER",
    }
    assert result["refrigerated_shipments"] == 100
    assert result["hazardous_shipments"] == 50
    assert result["anomaly_distribution"]["BASELINE"] == 995
    assert result["exception_distribution"] == {}
    assert (
        sum(result["rejection_reason_distribution"].values())
        == result["rejected_appointments"]
    )

    app = _generator_app(database_path)
    with app.app_context():
        validation = validation_summary(db.session)
        assert validation["foreign_key_integrity"] is True
        assert validation["lifecycle_histories_valid"] is True
        assert validation["timeline_ordering"] is True
        assert validation["ground_truth_label_consistency"] is True
        assert validation["dock_capacity_valid"] is True
        assert validation["yard_capacity_valid"] is True
        assert validation["labor_capacity_valid"] is True
        assert validation["handling_compatibility_valid"] is True
        resource_checks = resource_capacity_summary(db.session)
        assert len(resource_checks["dock"]["over_capacity_appointment_ids"]) == 2
        assert resource_checks["dock"]["unintended_over_capacity_appointment_ids"] == []
        assert len(resource_checks["labor"]["over_capacity_appointment_ids"]) == 1
        assert resource_checks["labor"]["unintended_over_capacity_appointment_ids"] == []
        assert resource_checks["labor"]["assignments_on_anomaly_shift"] == 1
        assert db.session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM shipments s
                JOIN vehicles v ON v.id = s.vehicle_id
                WHERE s.carrier_id != v.carrier_id
                """
            )
        ).scalar_one() == 0
        assert db.session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM appointments a
                JOIN shipments s ON s.id = a.shipment_id
                WHERE a.facility_id != s.facility_id
                """
            )
        ).scalar_one() == 0
        assert db.session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM appointments a
                JOIN shipments s ON s.id = a.shipment_id
                LEFT JOIN vehicles v ON v.id = s.vehicle_id
                WHERE v.id IS NULL
                   OR s.weight_kg > v.capacity_kg
                """
            )
        ).scalar_one() == 0

        facility_carrier_pairs = db.session.execute(
            text(
                """
                SELECT s.facility_id, s.carrier_id, COUNT(*)
                FROM appointments a
                JOIN shipments s ON s.id = a.shipment_id
                GROUP BY s.facility_id, s.carrier_id
                """
            )
        ).all()
        assert len({facility_id for facility_id, _, _ in facility_carrier_pairs}) == 10
        assert len({carrier_id for _, carrier_id, _ in facility_carrier_pairs}) == 20
        assert len(facility_carrier_pairs) == 200
        assert all(pair_count > 0 for _, _, pair_count in facility_carrier_pairs)

        allocations = (
            db.session.query(Appointment)
            .filter_by(status="SCHEDULED")
            .all()
        )
        assert len(allocations) == result["scheduled_appointments"]
        for appointment in allocations:
            assert len(
                [
                    reservation
                    for reservation in appointment.dock_reservations
                    if reservation.status == "ACTIVE"
                ]
            ) == 1
            assert len(
                [
                    reservation
                    for reservation in appointment.yard_slot_reservations
                    if reservation.status == "ACTIVE"
                ]
            ) == 1
            assert len(
                [
                    assignment
                    for assignment in LaborAssignment.query.filter_by(
                        appointment_id=appointment.id
                    )
                ]
            ) == 1

        anomaly_appointments = {
            label.appointment_id
            for label in AnomalyLabel.query.filter(
                AnomalyLabel.label != "BASELINE"
            ).all()
        }
        for appointment in allocations:
            if appointment.id in anomaly_appointments:
                continue
            requirement = HandlingRequirement.query.filter_by(
                shipment_id=appointment.shipment_id
            ).one()
            reservation = next(
                row
                for row in appointment.dock_reservations
                if row.status == "ACTIVE"
            )
            assert handles_requirement(
                reservation.dock.dock_type,
                requirement,
            )
            yard_reservation = next(
                row
                for row in appointment.yard_slot_reservations
                if row.status == "ACTIVE"
            )
            assert yard_reservation.yard_slot.slot_type == handling_yard_slot_type(
                requirement
            )

        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []


def test_actual_dock_utilization_outcomes_wait_and_reconciliation(
    temporary_app,
):
    report_start = datetime(2026, 10, 30, 6, tzinfo=timezone.utc)
    report_end = datetime(2026, 10, 30, 22, tzinfo=timezone.utc)
    with temporary_app.app_context():
        facility = Facility(
            code="METRICS",
            name="Metrics Facility",
            operating_start=time(6),
            operating_end=time(22),
        )
        carrier = Carrier(code="METRICS-C", name="Metrics Carrier")
        db.session.add_all([facility, carrier])
        db.session.flush()
        docks = [
            Dock(facility_id=facility.id, code=f"METRICS-D{index}")
            for index in range(1, 3)
        ]
        vehicle = Vehicle(
            carrier_id=carrier.id,
            registration="METRICS-V",
            vehicle_type="TRUCK",
        )
        db.session.add_all(docks + [vehicle])
        db.session.flush()

        statuses = ("SCHEDULED", "SCHEDULED", "CANCELLED", "REJECTED")
        appointments = []
        timelines = []
        for index, status in enumerate(statuses, 1):
            shipment = Shipment(
                reference=f"METRICS-S{index}",
                facility_id=facility.id,
                carrier_id=carrier.id,
                vehicle_id=vehicle.id,
                direction="INBOUND",
                weight_kg=1000,
            )
            db.session.add(shipment)
            db.session.flush()
            appointment = Appointment(
                reference=f"METRICS-A{index}",
                shipment_id=shipment.id,
                facility_id=facility.id,
                requested_start=report_start + timedelta(hours=4),
                requested_end=report_start + timedelta(hours=6),
                duration_minutes=60,
                status=status,
            )
            db.session.add(appointment)
            db.session.flush()
            appointments.append(appointment)
            if index <= 2:
                dock_arrival = report_start + timedelta(hours=2, minutes=60 * (index - 1))
                service_end = dock_arrival + timedelta(hours=2)
                arrival = dock_arrival - timedelta(minutes=10)
                db.session.add(
                    DockReservation(
                        dock_id=docks[0].id,
                        appointment_id=appointment.id,
                        start_at=dock_arrival,
                        end_at=service_end,
                        status="ACTIVE",
                    )
                )
                timelines.append(
                    AppointmentTimeline(
                        appointment_id=appointment.id,
                        actual_arrival_at=arrival,
                        yard_entry_at=arrival + timedelta(minutes=5),
                        dock_arrival_at=dock_arrival,
                        service_start_at=dock_arrival + timedelta(minutes=20),
                        service_end_at=service_end,
                        departure_at=service_end + timedelta(minutes=30),
                    )
                )
            else:
                db.session.add(
                    DockReservation(
                        dock_id=docks[1].id,
                        appointment_id=appointment.id,
                        start_at=report_start + timedelta(hours=1),
                        end_at=report_start + timedelta(hours=14),
                        status="CANCELLED",
                    )
                )
                timelines.append(
                    AppointmentTimeline(
                        appointment_id=appointment.id,
                        actual_arrival_at=report_start + timedelta(hours=1),
                        dock_arrival_at=report_start + timedelta(hours=2),
                        service_start_at=report_start + timedelta(hours=2),
                        service_end_at=report_start + timedelta(hours=14),
                    )
                )

        db.session.add_all(timelines)
        db.session.add_all(
            [
                SchedulingDecision(
                    appointment_id=appointments[0].id,
                    decision="ACCEPTED",
                    reason_code="ALLOCATED",
                    details={},
                ),
                SchedulingDecision(
                    appointment_id=appointments[1].id,
                    decision="ACCEPTED",
                    reason_code="ALLOCATED",
                    details={},
                ),
                SchedulingDecision(
                    appointment_id=appointments[3].id,
                    decision="REJECTED",
                    reason_code="DOCK_UNAVAILABLE",
                    details={},
                ),
                OperationalException(
                    appointment_id=appointments[0].id,
                    facility_id=facility.id,
                    severity="MEDIUM",
                    cause_code="LATE_ARRIVAL",
                    description="Late arrival",
                    status="OPEN",
                ),
                OperationalException(
                    appointment_id=appointments[1].id,
                    facility_id=facility.id,
                    severity="LOW",
                    cause_code="DOCK_DELAY",
                    description="Resolved dock delay",
                    status="RESOLVED",
                ),
            ]
        )
        db.session.commit()

        utilization = dock_utilization_metrics(report_start, report_end)
        timeline = timeline_metrics()
        evaluation = evaluation_metrics()
        dashboard = dashboard_metrics()
        status_counts = appointment_status_counts()

        assert utilization["occupied_dock_minutes"] == 180.0
        assert utilization["available_dock_minutes"] == 1920.0
        assert utilization["dock_utilization"] == 9.38
        assert dashboard["dock_utilization"] == 9.38
        assert timeline["wait_time_minutes"] == 30.0
        assert timeline["dock_occupied_minutes"] == 240.0
        assert timeline["timeline_sample_size"] == 2
        assert evaluation["appointment_count"] == 4
        assert evaluation["accepted_decisions"] == 2
        assert evaluation["rejected_decisions"] == 1
        assert evaluation["exception_count"] == 2
        assert evaluation["open_exception_count"] == 1
        assert status_counts == {
            "CANCELLED": 1,
            "REJECTED": 1,
            "SCHEDULED": 2,
        }
        reconciliation = reconcile(
            evaluation["appointment_count"],
            sum(status_counts.values()),
        )
        assert reconciliation == {
            "expected": 4,
            "actual": 4,
            "difference": 0,
        }
