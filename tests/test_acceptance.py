from datetime import datetime, timedelta, timezone

from app import db
from sqlalchemy import text
from app.models.domain import AppointmentTimeline, YardSlot
from app.models.events import LifecycleEvent, OperationalException
from app.models.masters import Carrier, Dock, Facility, LaborShift, Vehicle
from app.models.operations import Appointment, Shipment
from app.models.scheduling import SchedulingDecision
from app.services.scheduler import schedule_appointment
from app.services.metrics import timeline_metrics
from app.services.simulator import simulate_appointments
from generator.anomalies import appointment_arrival_label
from generator.generate import generate
from validation.scenario_evaluator import evaluate
from validation.timelines import timeline_ordered
from validation.validate import validation_summary
from validation.capacities import resource_capacity_summary


def test_negative_scenario_evaluator_passes_all_cases():
    results = evaluate("sqlite:///:memory:")
    assert len(results) == 5
    assert all(result["pass"] for result in results)
    assert {
        result["scenario_id"]: result["actual_code"]
        for result in results
        if result["scenario_id"] != "NEG-005"
    } == {
        "NEG-001": "DOCK_UNAVAILABLE",
        "NEG-002": "DOCK_INCOMPATIBLE",
        "NEG-003": "EARLY_CHECK_IN",
        "NEG-004": "LABOR_UNAVAILABLE",
    }


def test_generated_arrival_label_matches_its_timestamps():
    scheduled = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
    assert appointment_arrival_label(
        scheduled - timedelta(minutes=10), scheduled
    ) == "BASELINE"
    assert appointment_arrival_label(
        scheduled + timedelta(minutes=20), scheduled
    ) == "LATE_ARRIVAL"


def test_timeline_validation_checks_order_and_allows_missing_milestones():
    start = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
    valid = AppointmentTimeline(
        actual_arrival_at=start,
        service_start_at=start + timedelta(minutes=10),
        departure_at=start + timedelta(hours=2),
    )
    invalid = AppointmentTimeline(
        actual_arrival_at=start,
        service_start_at=start + timedelta(minutes=10),
        departure_at=start + timedelta(minutes=5),
    )
    assert timeline_ordered(valid)
    assert not timeline_ordered(invalid)


def test_validation_summary_reports_fk_and_timeline_checks(app):
    with app.app_context():
        summary = validation_summary(db.session)

    assert summary["foreign_key_integrity"] is True
    assert summary["timeline_table_present"] is True
    assert summary["timeline_ordering"] is True


def test_starter_generator_labels_real_anomalies_in_isolated_database(tmp_path):
    database_path = tmp_path / "generator.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    result = generate(
        seed=20261022,
        mode="starter",
        database_url=database_url,
    )
    assert result["appointments"] == 40
    assert set(result["anomalies"]) == {
        "DOCK_CAPACITY_EXCEEDED",
        "INCOMPATIBLE_LOAD_ASSIGNMENT",
        "CHECK_IN_BEFORE_APPOINTMENT_DATE",
        "LABOR_UNAVAILABLE",
        "NO_SHOW_NOT_RECORDED",
    }

    GeneratorConfig = type(
        "GeneratorConfig",
        (),
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": database_url,
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "SQLALCHEMY_ENGINE_OPTIONS": {},
        },
    )
    from app import create_app
    from app.models.domain import CheckInEvent, HandlingRequirement
    from app.models.events import AnomalyLabel, GroundTruthRecord, LifecycleEvent
    from app.models.masters import LaborAssignment, LaborShift
    from app.models.operations import Appointment
    from app.models.scheduling import DockReservation
    from validation.validate import validation_summary

    app = create_app(GeneratorConfig)
    with app.app_context():
        labels = {
            row.label: row.appointment_id
            for row in AnomalyLabel.query.filter(
                AnomalyLabel.label != "BASELINE"
            ).all()
        }
        assert set(labels) == set(result["anomalies"])
        for issue_type, appointment_id in labels.items():
            truth = GroundTruthRecord.query.filter_by(
                entity_type="appointment",
                entity_id=appointment_id,
            ).one()
            assert truth.truth["issue_type"] == issue_type

        dock_appointment = db.session.get(
            Appointment,
            labels["DOCK_CAPACITY_EXCEEDED"],
        )
        dock_reservation = DockReservation.query.filter_by(
            appointment_id=dock_appointment.id,
            status="ACTIVE",
        ).one()
        assert DockReservation.query.filter(
            DockReservation.dock_id == dock_reservation.dock_id,
            DockReservation.status == "ACTIVE",
            DockReservation.start_at < dock_reservation.end_at,
            DockReservation.end_at > dock_reservation.start_at,
            DockReservation.appointment_id != dock_appointment.id,
        ).count() == 1

        dock_truth = GroundTruthRecord.query.filter_by(
            entity_type="appointment",
            entity_id=dock_appointment.id,
        ).one().truth
        conflicting_id = dock_truth["conflicting_appointment_id"]
        conflict_rows = db.session.execute(
            text(
                """
                SELECT first_reservation.appointment_id,
                       second_reservation.appointment_id
                FROM dock_reservations first_reservation
                JOIN dock_reservations second_reservation
                  ON second_reservation.dock_id = first_reservation.dock_id
                 AND second_reservation.appointment_id >
                     first_reservation.appointment_id
                 AND second_reservation.status = 'ACTIVE'
                 AND first_reservation.start_at < second_reservation.end_at
                 AND first_reservation.end_at > second_reservation.start_at
                WHERE first_reservation.status = 'ACTIVE'
                """
            )
        ).all()
        assert {
            frozenset((first_id, second_id))
            for first_id, second_id in conflict_rows
        } == {frozenset((dock_appointment.id, conflicting_id))}

        incompatible = db.session.get(
            Appointment,
            labels["INCOMPATIBLE_LOAD_ASSIGNMENT"],
        )
        requirement = HandlingRequirement.query.filter_by(
            shipment_id=incompatible.shipment_id
        ).one()
        incompatible_reservation = DockReservation.query.filter_by(
            appointment_id=incompatible.id,
            status="ACTIVE",
        ).one()
        assert requirement.refrigerated or requirement.hazardous
        assert incompatible_reservation.dock.dock_type == "GENERAL"
        assert DockReservation.query.filter(
            DockReservation.dock_id == incompatible_reservation.dock_id,
            DockReservation.status == "ACTIVE",
            DockReservation.start_at < incompatible_reservation.end_at,
            DockReservation.end_at > incompatible_reservation.start_at,
            DockReservation.appointment_id != incompatible.id,
        ).count() == 0

        early = CheckInEvent.query.filter_by(
            appointment_id=labels["CHECK_IN_BEFORE_APPOINTMENT_DATE"],
            outcome="REJECTED",
            reason_code="EARLY_CHECK_IN",
        ).one()
        early_appointment = db.session.get(Appointment, early.appointment_id)
        assert early.attempted_at < early_appointment.scheduled_start

        labor_appointment = db.session.get(
            Appointment,
            labels["LABOR_UNAVAILABLE"],
        )
        assignment = LaborAssignment.query.filter_by(
            appointment_id=labor_appointment.id
        ).one()
        shift = db.session.get(LaborShift, assignment.shift_id)
        assert shift.workers < assignment.workers
        labor_truth = GroundTruthRecord.query.filter_by(
            entity_type="appointment",
            entity_id=labor_appointment.id,
        ).one().truth
        recurring_shift = db.session.get(
            LaborShift,
            labor_truth["recurring_shift_id"],
        )
        assert recurring_shift.workers == 12
        assert LaborAssignment.query.filter_by(
            shift_id=recurring_shift.id
        ).count() > 0
        assert LaborAssignment.query.filter_by(
            shift_id=shift.id
        ).count() == 1

        no_show = db.session.get(
            Appointment,
            labels["NO_SHOW_NOT_RECORDED"],
        )
        truth = GroundTruthRecord.query.filter_by(
            entity_type="appointment",
            entity_id=no_show.id,
        ).one().truth
        assert no_show.status == "SCHEDULED"
        assert no_show.requested_end.isoformat() == truth["requested_end"]
        assert truth["requested_end"] < truth["snapshot_at"]
        assert LifecycleEvent.query.filter_by(
            appointment_id=no_show.id,
            to_status="NO_SHOW",
        ).count() == 0
        resource_checks = resource_capacity_summary(db.session)
        assert resource_checks["dock"]["over_capacity_appointment_ids"] == sorted(
            (dock_appointment.id, conflicting_id)
        )
        assert resource_checks["dock"]["unintended_over_capacity_appointment_ids"] == []
        assert resource_checks["labor"]["over_capacity_appointment_ids"] == [
            labor_appointment.id
        ]
        assert resource_checks["labor"]["unintended_over_capacity_appointment_ids"] == []
        assert resource_checks["yard"]["slot_over_capacity_appointment_ids"] == []
        assert resource_checks["yard"]["facility_over_capacity_appointment_ids"] == []
        validation = validation_summary(db.session)
        assert validation["dock_capacity_valid"]
        assert validation["labor_capacity_valid"]
        assert validation["yard_capacity_valid"]
        assert validation["handling_compatibility_valid"]
        assert validation["ground_truth_label_consistency"]
        assert OperationalException.query.count() == 0

        summary = validation_summary(db.session)
        assert summary["ground_truth_label_consistency"] is True
        assert summary["lifecycle_histories_valid"] is True
        assert summary["timeline_ordering"] is True


def test_timeline_metrics_exclude_missing_endpoints(app):
    with app.app_context():
        now = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
        facility = Facility(code="TIMELINE", name="Timeline Facility")
        carrier = Carrier(code="TIMELINE-C", name="Timeline Carrier")
        db.session.add_all([facility, carrier])
        db.session.flush()
        vehicle = Vehicle(
            carrier_id=carrier.id,
            registration="TIMELINE-V",
            vehicle_type="TRUCK",
        )
        db.session.add(vehicle)
        db.session.flush()
        shipment = Shipment(
            reference="TIMELINE-S",
            facility_id=facility.id,
            carrier_id=carrier.id,
            vehicle_id=vehicle.id,
            direction="INBOUND",
            weight_kg=1000,
        )
        db.session.add(shipment)
        db.session.flush()
        appointments = [
            Appointment(
                reference=f"TIMELINE-A{index}",
                shipment_id=shipment.id,
                facility_id=facility.id,
                requested_start=now,
                requested_end=now + timedelta(hours=2),
                duration_minutes=60,
                status="SCHEDULED",
            )
            for index in range(1, 3)
        ]
        db.session.add_all(appointments)
        db.session.flush()
        # These rows are metric fixtures only; missing endpoints must not be fabricated.
        db.session.add(AppointmentTimeline(appointment_id=appointments[0].id, actual_arrival_at=now,
                                           service_start_at=now + timedelta(minutes=15),
                                           dock_arrival_at=now + timedelta(minutes=10),
                                           service_end_at=now + timedelta(minutes=75),
                                           yard_entry_at=now, departure_at=now + timedelta(minutes=90)))
        db.session.add(AppointmentTimeline(appointment_id=appointments[1].id))
        db.session.commit()
        metrics = timeline_metrics()
        assert metrics["wait_time_minutes"] == 15.0
        assert metrics["dock_occupied_minutes"] == 65.0
        assert metrics["yard_occupied_minutes"] == 90.0
        assert metrics["timeline_sample_size"] == 2


def test_simulation_outputs_are_deterministic_and_do_not_write(app):
    with app.app_context():
        facility = Facility(code="SIM-F", name="Simulation Facility")
        carrier = Carrier(code="SIM-C", name="Simulation Carrier")
        db.session.add_all([facility, carrier]); db.session.flush()
        db.session.add_all([
            Dock(facility_id=facility.id, code="SIM-D"),
            LaborShift(facility_id=facility.id, name="Day", start_time=datetime.min.time(), end_time=datetime.max.time(), workers=5),
            YardSlot(facility_id=facility.id, code="SIM-Y", capacity=5),
        ])
        vehicle = Vehicle(carrier_id=carrier.id, registration="SIM-V", vehicle_type="TRUCK")
        db.session.add(vehicle); db.session.flush()
        shipment = Shipment(reference="SIM-S", facility_id=facility.id, carrier_id=carrier.id,
                            vehicle_id=vehicle.id, direction="OUTBOUND", weight_kg=1000)
        db.session.add(shipment); db.session.flush()
        start = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
        appointment = Appointment(reference="SIM-A", shipment_id=shipment.id, facility_id=facility.id,
                                  requested_start=start, requested_end=start + timedelta(hours=3),
                                  duration_minutes=60)
        db.session.add(appointment); db.session.commit()
        assert schedule_appointment(appointment) is not None
        before = (Appointment.query.count(), SchedulingDecision.query.count(), LifecycleEvent.query.count())

        first = simulate_appointments(seed=55)
        second = simulate_appointments(seed=55)

        after = (Appointment.query.count(), SchedulingDecision.query.count(), LifecycleEvent.query.count())
        assert first == second
        assert first["appointment_count"] == 1
        assert first["scheduled_count"] == 1
        assert first["projected_service_minutes"] > 0
        assert first["within_window_count"] == 1
        assert before == after
