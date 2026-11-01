from datetime import datetime, time, timedelta, timezone

import pytest

from app import db
from app.models.domain import AppointmentTimeline
from app.models.events import OperationalException
from app.models.masters import Carrier, Dock, Facility, LaborShift, Vehicle
from app.models.operations import Appointment, Shipment
from app.models.scheduling import DockReservation, SchedulingDecision
from app.services.exception_detector import detect_arrival
from app.services.metrics import dock_utilization_metrics, throughput_metrics
from app.services.operational_exceptions import record_scheduling_exception


def _appointment(facility, carrier, vehicle, reference, status="SCHEDULED"):
    shipment = Shipment(
        reference=f"S-{reference}",
        facility_id=facility.id,
        carrier_id=carrier.id,
        vehicle_id=vehicle.id,
        direction="INBOUND",
        weight_kg=100,
    )
    db.session.add(shipment)
    db.session.flush()
    appointment = Appointment(
        reference=reference,
        shipment_id=shipment.id,
        facility_id=facility.id,
        requested_start=datetime(2026, 10, 30, 6, tzinfo=timezone.utc),
        requested_end=datetime(2026, 10, 30, 22, tzinfo=timezone.utc),
        duration_minutes=60,
        status=status,
    )
    db.session.add(appointment)
    db.session.flush()
    return appointment


def test_throughput_counts_actual_terminal_events_by_day_and_facility(app):
    with app.app_context():
        facility = Facility(code="TP-F", name="Throughput")
        carrier = Carrier(code="TP-C", name="Throughput Carrier")
        db.session.add_all([facility, carrier])
        db.session.flush()
        vehicle = Vehicle(
            carrier_id=carrier.id,
            registration="TP-V",
            vehicle_type="TRUCK",
        )
        db.session.add(vehicle)
        db.session.flush()
        completed = _appointment(facility, carrier, vehicle, "TP-COMP", "COMPLETED")
        departed = _appointment(facility, carrier, vehicle, "TP-DEPT", "DEPARTED")
        _appointment(facility, carrier, vehicle, "TP-SCHED", "SCHEDULED")
        db.session.add_all([
            AppointmentTimeline(
                appointment_id=completed.id,
                service_end_at=datetime(2026, 10, 30, 10, tzinfo=timezone.utc),
            ),
            AppointmentTimeline(
                appointment_id=departed.id,
                service_end_at=datetime(2026, 10, 31, 10, tzinfo=timezone.utc),
                departure_at=datetime(2026, 10, 31, 11, tzinfo=timezone.utc),
            ),
        ])
        db.session.commit()

        result = throughput_metrics(
            datetime(2026, 10, 30, tzinfo=timezone.utc),
            datetime(2026, 11, 1, tzinfo=timezone.utc),
            facility_id=facility.id,
        )

        assert result["throughput_count"] == 2
        assert result["completed_count"] == 1
        assert result["departed_count"] == 1
        assert result["daily"] == {"2026-10-30": 1, "2026-10-31": 1}
        assert result["by_facility"] == {str(facility.id): 2}


def test_dock_utilization_clips_boundaries_and_unions_overlaps(app):
    with app.app_context():
        facility = Facility(
            code="DU-F",
            name="Dock Utilization",
            operating_start=time(6),
            operating_end=time(22),
        )
        carrier = Carrier(code="DU-C", name="Dock Carrier")
        db.session.add_all([facility, carrier])
        db.session.flush()
        docks = [
            Dock(facility_id=facility.id, code="DU-1"),
            Dock(facility_id=facility.id, code="DU-2"),
        ]
        vehicle = Vehicle(
            carrier_id=carrier.id,
            registration="DU-V",
            vehicle_type="TRUCK",
        )
        db.session.add_all(docks + [vehicle])
        db.session.flush()
        intervals = [
            ("DU-A", docks[0], datetime(2026, 10, 30, 5, tzinfo=timezone.utc), datetime(2026, 10, 30, 8, tzinfo=timezone.utc)),
            ("DU-B", docks[0], datetime(2026, 10, 30, 7, tzinfo=timezone.utc), datetime(2026, 10, 30, 10, tzinfo=timezone.utc)),
            ("DU-C", docks[1], datetime(2026, 10, 30, 21, tzinfo=timezone.utc), datetime(2026, 10, 30, 23, tzinfo=timezone.utc)),
        ]
        for reference, dock, start, end in intervals:
            appointment = _appointment(facility, carrier, vehicle, reference)
            db.session.add(DockReservation(
                dock_id=dock.id,
                appointment_id=appointment.id,
                start_at=start,
                end_at=end,
                status="ACTIVE",
            ))
            db.session.add(AppointmentTimeline(
                appointment_id=appointment.id,
                dock_arrival_at=start,
                service_end_at=end,
            ))
        db.session.commit()

        result = dock_utilization_metrics(
            datetime(2026, 10, 30, 6, tzinfo=timezone.utc),
            datetime(2026, 10, 30, 22, tzinfo=timezone.utc),
        )

        # Dock 1 is one union [06:00, 10:00] = 240 minutes; dock 2 contributes
        # [21:00, 22:00] = 60 minutes. Two docks x 16 hours = 1,920 minutes.
        assert result["occupied_dock_minutes"] == 300.0
        assert result["available_dock_minutes"] == 1920.0
        assert result["dock_utilization"] == 15.62


def test_scheduling_exception_causes_are_meaningful_and_deduplicated(app):
    with app.app_context():
        facility = Facility(code="EX-F", name="Exceptions")
        carrier = Carrier(code="EX-C", name="Exception Carrier")
        db.session.add_all([facility, carrier])
        db.session.flush()
        vehicle = Vehicle(
            carrier_id=carrier.id,
            registration="EX-V",
            vehicle_type="TRUCK",
        )
        db.session.add(vehicle)
        db.session.flush()
        appointment = _appointment(facility, carrier, vehicle, "EX-A")

        record_scheduling_exception(appointment, "DOCK_UNAVAILABLE")
        record_scheduling_exception(appointment, "DOCK_UNAVAILABLE")
        db.session.commit()

        rows = OperationalException.query.filter_by(appointment_id=appointment.id).all()
        assert len(rows) == 1
        assert rows[0].cause_code == "PEAK_CONGESTION"
        assert rows[0].status == "OPEN"


@pytest.mark.parametrize(
    ("reason_code", "cause_code"),
    [
        ("DOCK_UNAVAILABLE", "PEAK_CONGESTION"),
        ("DOCK_INCOMPATIBLE", "INCOMPATIBLE_LOAD"),
        ("LABOR_UNAVAILABLE", "LABOR_UNAVAILABLE"),
        ("INVALID_STATUS", "INVALID_SCHEDULING_DECISION"),
    ],
)
def test_scheduling_failure_scenarios_map_to_operational_causes(app, reason_code, cause_code):
    with app.app_context():
        facility = Facility(code=f"MAP-{reason_code[:3]}", name="Mapping")
        carrier = Carrier(code=f"MAP-{reason_code[-3:]}", name="Mapping Carrier")
        db.session.add_all([facility, carrier])
        db.session.flush()
        vehicle = Vehicle(
            carrier_id=carrier.id,
            registration=f"MAP-{reason_code[:3]}",
            vehicle_type="TRUCK",
        )
        db.session.add(vehicle)
        db.session.flush()
        appointment = _appointment(facility, carrier, vehicle, f"MAP-{reason_code}")

        record_scheduling_exception(appointment, reason_code)
        db.session.commit()

        row = OperationalException.query.filter_by(appointment_id=appointment.id).one()
        assert row.cause_code == cause_code
        assert row.status == "OPEN"


def test_late_arrival_exception_is_resolvable_and_traceable(app):
    with app.app_context():
        facility = Facility(code="LATE-F", name="Late")
        carrier = Carrier(code="LATE-C", name="Late Carrier")
        db.session.add_all([facility, carrier])
        db.session.flush()
        vehicle = Vehicle(
            carrier_id=carrier.id,
            registration="LATE-V",
            vehicle_type="TRUCK",
        )
        db.session.add(vehicle)
        db.session.flush()
        appointment = _appointment(facility, carrier, vehicle, "LATE-A")
        appointment.scheduled_start = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
        db.session.commit()

        exception = detect_arrival(
            appointment,
            datetime(2026, 10, 30, 10, 20, tzinfo=timezone.utc),
        )

        assert exception is not None
        assert exception.cause_code == "LATE_ARRIVAL"
        exception.status = "RESOLVED"
        exception.resolved_at = datetime(2026, 10, 30, 10, 21, tzinfo=timezone.utc)
        exception.resolution_notes = "Reviewed"
        db.session.commit()
        stored = db.session.get(OperationalException, exception.id)
        assert stored.status == "RESOLVED"
        assert stored.resolved_at is not None
        assert stored.resolution_notes == "Reviewed"
