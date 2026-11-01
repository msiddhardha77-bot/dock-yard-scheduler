from datetime import timedelta


def _utc(value):
    from datetime import timezone

    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def label_late_arrival(minutes_late):
    return "LATE_ARRIVAL" if minutes_late > 15 else None


def appointment_arrival_label(actual_arrival, scheduled_start):
    minutes_late = (actual_arrival - scheduled_start).total_seconds() / 60
    return label_late_arrival(minutes_late) or "BASELINE"


def inject_anomalies(snapshot_at):
    """Apply deterministic, labelled anomalies after baseline scheduling."""
    from app import db
    from app.models.domain import CheckInEvent, HandlingRequirement
    from app.models.events import AnomalyLabel, GroundTruthRecord, LifecycleEvent
    from app.models.masters import Dock, LaborAssignment, LaborShift
    from app.models.operations import Appointment
    from app.models.scheduling import DockReservation

    appointments = (
        Appointment.query.filter_by(status="SCHEDULED")
        .order_by(Appointment.id)
        .all()
    )
    requirements = {
        row.shipment_id: row
        for row in HandlingRequirement.query.all()
    }
    reservations = {
        row.appointment_id: row
        for row in DockReservation.query.filter_by(status="ACTIVE").all()
    }
    assignments = {
        row.appointment_id: row
        for row in LaborAssignment.query.all()
    }
    used_ids = set()

    def overlaps(first, second):
        return first.start_at < second.end_at and first.end_at > second.start_at

    def label(appointment, issue_type, **evidence):
        labels = AnomalyLabel.query.filter_by(
            appointment_id=appointment.id
        ).order_by(AnomalyLabel.id).all()
        truth = GroundTruthRecord.query.filter_by(
            entity_type="appointment",
            entity_id=appointment.id,
        ).first()
        if not labels or truth is None:
            raise RuntimeError(
                f"Missing baseline label or ground truth for {appointment.reference}"
            )
        labels[0].label = issue_type
        truth.truth = {
            **(truth.truth or {}),
            "issue_type": issue_type,
            "label": issue_type,
            **evidence,
        }
        used_ids.add(appointment.id)

    # Select a pair whose reassignment creates exactly one isolated overlap.
    reservations_by_id = sorted(
        reservations.values(),
        key=lambda row: (row.start_at, row.end_at, row.id),
    )
    appointment_by_id = {row.id: row for row in appointments}
    dock_conflict = None
    for affected_reservation in reservations_by_id:
        affected_appointment = appointment_by_id[affected_reservation.appointment_id]
        for conflicting_reservation in reservations_by_id:
            if (
                conflicting_reservation.dock_id == affected_reservation.dock_id
                or not overlaps(affected_reservation, conflicting_reservation)
            ):
                continue
            conflicting_appointment = appointment_by_id[
                conflicting_reservation.appointment_id
            ]
            if affected_appointment.facility_id != conflicting_appointment.facility_id:
                continue
            overlapping_reservations = [
                row
                for row in reservations_by_id
                if row.appointment_id != affected_reservation.appointment_id
                and row.dock_id == conflicting_reservation.dock_id
                and overlaps(affected_reservation, row)
            ]
            if (
                len(overlapping_reservations) == 1
                and overlapping_reservations[0].appointment_id
                == conflicting_reservation.appointment_id
            ):
                dock_conflict = (affected_reservation, conflicting_reservation)
                break
        if dock_conflict is not None:
            break
    if dock_conflict is None:
        raise RuntimeError(
            "Could not find a dock reassignment that creates exactly one "
            "isolated capacity conflict"
        )
    affected_reservation, conflicting_reservation = dock_conflict
    affected_reservation.dock_id = conflicting_reservation.dock_id
    used_ids.add(conflicting_reservation.appointment_id)
    label(
        db.session.get(Appointment, affected_reservation.appointment_id),
        "DOCK_CAPACITY_EXCEEDED",
        conflicting_appointment_id=conflicting_reservation.appointment_id,
        dock_id=conflicting_reservation.dock_id,
    )

    # Assign a special-handling shipment to an otherwise idle general dock.
    incompatible = None
    docks_by_facility = {}
    for dock in Dock.query.filter_by(active=True).order_by(Dock.code).all():
        docks_by_facility.setdefault(dock.facility_id, []).append(dock)
    for appointment in appointments:
        if appointment.id in used_ids:
            continue
        requirement = requirements.get(appointment.shipment_id)
        reservation = reservations.get(appointment.id)
        if not requirement or not reservation:
            continue
        if not (requirement.refrigerated or requirement.hazardous):
            continue
        general_dock = next(
            (
                dock
                for dock in docks_by_facility.get(appointment.facility_id, ())
                if dock.dock_type == "GENERAL"
                and not any(
                    row.appointment_id != appointment.id
                    and row.dock_id == dock.id
                    and overlaps(reservation, row)
                    for row in reservations_by_id
                )
            ),
            None,
        )
        if general_dock:
            incompatible = (appointment, reservation, general_dock)
            break
    if incompatible is None:
        raise RuntimeError("Could not find a special-handling appointment and general dock")
    appointment, reservation, general_dock = incompatible
    reservation.dock_id = general_dock.id
    label(
        appointment,
        "INCOMPATIBLE_LOAD_ASSIGNMENT",
        dock_id=general_dock.id,
        required_refrigerated=requirements[appointment.shipment_id].refrigerated,
        required_hazardous=requirements[appointment.shipment_id].hazardous,
    )

    early_arrival = next(
        (
            appointment for appointment in appointments
            if appointment.id not in used_ids
            and appointment.id in reservations
            and CheckInEvent.query.filter_by(
                appointment_id=appointment.id
            ).count() == 0
        ),
        None,
    )
    if early_arrival is None:
        raise RuntimeError("Could not find an appointment for the early-check-in anomaly")
    attempt_number = 1
    attempted_at = early_arrival.scheduled_start - timedelta(days=1)
    db.session.add(CheckInEvent(
        event_reference=f"CHECK-{early_arrival.id}-{attempt_number:02d}",
        appointment_id=early_arrival.id,
        attempt_number=attempt_number,
        attempted_at=attempted_at,
        outcome="REJECTED",
        reason_code="EARLY_CHECK_IN",
    ))
    label(
        early_arrival,
        "CHECK_IN_BEFORE_APPOINTMENT_DATE",
        attempted_at=attempted_at.isoformat(),
        scheduled_start=early_arrival.scheduled_start.isoformat(),
    )

    labor_case = next((
        appointment
        for appointment in appointments
        if appointment.id not in used_ids
        and appointment.id in assignments
        and requirements.get(appointment.shipment_id)
        and requirements[appointment.shipment_id].required_workers > 1
    ), None)
    if labor_case is None:
        raise RuntimeError(
            "Could not find a multi-worker appointment for the labor anomaly"
        )
    assignment = assignments[labor_case.id]
    shift = LaborShift.query.filter_by(id=assignment.shift_id).one()
    anomaly_shift = LaborShift(
        facility_id=labor_case.facility_id,
        name=f"ANOMALY-{labor_case.reference}",
        start_time=labor_case.scheduled_start.time().replace(tzinfo=None),
        end_time=labor_case.scheduled_end.time().replace(tzinfo=None),
        workers=assignment.workers - 1,
    )
    db.session.add(anomaly_shift)
    db.session.flush()
    assignment.shift_id = anomaly_shift.id
    label(
        labor_case,
        "LABOR_UNAVAILABLE",
        shift_id=anomaly_shift.id,
        assigned_workers=assignment.workers,
        available_workers=anomaly_shift.workers,
        recurring_shift_id=shift.id,
        dedicated_shift_id=anomaly_shift.id,
    )

    no_show = next(
        (
            appointment for appointment in appointments
            if appointment.id not in used_ids
            and appointment.id in reservations
            and _utc(appointment.requested_end) < _utc(snapshot_at)
            and not LifecycleEvent.query.filter_by(
                appointment_id=appointment.id,
                to_status="NO_SHOW",
            ).first()
        ),
        None,
    )
    if no_show is None:
        raise RuntimeError("Could not find an overdue appointment for the no-show anomaly")
    label(
        no_show,
        "NO_SHOW_NOT_RECORDED",
        snapshot_at=snapshot_at.isoformat(),
        requested_end=no_show.requested_end.isoformat(),
    )

    db.session.flush()
    return [
        "DOCK_CAPACITY_EXCEEDED",
        "INCOMPATIBLE_LOAD_ASSIGNMENT",
        "CHECK_IN_BEFORE_APPOINTMENT_DATE",
        "LABOR_UNAVAILABLE",
        "NO_SHOW_NOT_RECORDED",
    ]
