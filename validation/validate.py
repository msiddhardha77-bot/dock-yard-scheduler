from sqlalchemy import inspect, text

from app.models.domain import AppointmentTimeline
from app.models.events import AnomalyLabel, GroundTruthRecord
from app.models.events import LifecycleEvent
from app.models.operations import Appointment
from validation.capacities import resource_capacity_summary
from validation.integrity import foreign_key_check
from validation.timelines import lifecycle_history_valid, timeline_ordered


def validate_appointments():
    errors = []
    for appointment in Appointment.query.all():
        if appointment.requested_end <= appointment.requested_start:
            errors.append((appointment.reference, "invalid_window"))
    return errors


def validation_summary(session):
    """Return database-backed integrity checks suitable for a manifest."""
    checks = {}
    checks["appointment_windows"] = len(validate_appointments()) == 0
    checks["orphan_lifecycle_events"] = session.execute(text(
        "select count(*) from lifecycle_events e left join appointments a on a.id=e.appointment_id where a.id is null"
    )).scalar() == 0
    checks["duplicate_appointment_references"] = session.execute(text(
        "select count(*) - count(distinct reference) from appointments"
    )).scalar() == 0
    checks["lifecycle_event_count"] = LifecycleEvent.query.count()
    invalid_lifecycle_histories = 0
    for appointment in Appointment.query.all():
        if not lifecycle_history_valid(appointment.events, appointment.status):
            invalid_lifecycle_histories += 1
    checks["invalid_lifecycle_histories"] = invalid_lifecycle_histories
    checks["lifecycle_histories_valid"] = invalid_lifecycle_histories == 0
    dialect = session.get_bind().dialect.name
    checks["foreign_key_integrity"] = (
        not foreign_key_check(session) if dialect == "sqlite" else None
    )
    has_timeline_table = inspect(session.get_bind()).has_table(
        AppointmentTimeline.__tablename__
    )
    checks["timeline_table_present"] = has_timeline_table
    checks["timeline_ordering"] = (
        all(
            timeline_ordered(timeline)
            for timeline in session.query(AppointmentTimeline).all()
        )
        if has_timeline_table else None
    )
    labels = AnomalyLabel.query.all()
    truth_by_appointment = {
        row.entity_id: row.truth
        for row in GroundTruthRecord.query.filter_by(entity_type="appointment").all()
    }
    checks["ground_truth_label_consistency"] = all(
        (truth_by_appointment.get(row.appointment_id) or {}).get(
            "issue_type",
            (truth_by_appointment.get(row.appointment_id) or {}).get("label"),
        ) == row.label
        for row in labels
    )
    capacities = resource_capacity_summary(session)
    checks["resource_capacity"] = capacities
    checks["dock_capacity_valid"] = (
        capacities["dock"]["intentional_evidence_valid"]
        and not capacities["dock"]["unintended_over_capacity_appointment_ids"]
        and not capacities["dock"]["assignment_violations"]
    )
    checks["yard_capacity_valid"] = (
        not capacities["yard"]["slot_over_capacity_appointment_ids"]
        and not capacities["yard"]["facility_over_capacity_appointment_ids"]
        and not capacities["yard"]["assignment_violations"]
    )
    checks["labor_capacity_valid"] = (
        capacities["labor"]["intentional_evidence_valid"]
        and not capacities["labor"]["unintended_over_capacity_appointment_ids"]
        and not capacities["labor"]["assignment_violations"]
    )
    checks["handling_compatibility_valid"] = (
        capacities["incompatible_handling"]["intentional_evidence_valid"]
        and not capacities["incompatible_handling"]["dock_assignment_violations"]
    )
    return checks
