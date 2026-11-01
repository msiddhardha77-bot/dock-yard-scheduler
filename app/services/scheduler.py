from datetime import timedelta

from app import db
from app.models.operations import Appointment
from app.models.scheduling import DockReservation, SchedulingDecision
from app.models.masters import Dock, Facility, LaborAssignment
from app.models.events import LifecycleEvent
from app.services.capacity import (
    available_dock,
    available_labor_shift,
    available_yard_slot,
    yard_available,
)
from app.services.compatibility import (
    compatible,
    handles_requirement,
    handling_yard_slot_type,
)
from app.services.reason_codes import explain
from app.services.operational_exceptions import record_scheduling_exception
from app.models.domain import HandlingRequirement, YardSlotReservation
from sqlalchemy import text


def _operating_hours(facility, start, end):
    return start.date() == end.date() and facility.operating_start <= start.time() and end.time() <= facility.operating_end


def _mysql_lock(dock_id):
    if db.engine.dialect.name != "mysql":
        return False
    name = f"dock-yard-scheduler:dock:{dock_id}"
    acquired = db.session.execute(text("SELECT GET_LOCK(:lock_name, 30)"), {"lock_name": name}).scalar()
    if acquired != 1:
        raise RuntimeError("Timed out acquiring the dock booking lock")
    return name


def _mysql_unlock(name):
    if name:
        db.session.execute(text("SELECT RELEASE_LOCK(:lock_name)"), {"lock_name": name})


def schedule_appointment(
    appointment,
    commit=True,
    decision_time=None,
    record_lifecycle=True,
    record_operational_exception=True,
):
    original_status = appointment.status
    if appointment.status not in {"REQUESTED", "REJECTED"}:
        return _reject(
            appointment,
            "INVALID_STATUS",
            commit,
            decision_time,
            record_lifecycle=False,
            update_status=False,
            record_operational_exception=record_operational_exception,
        )
    if original_status == "REJECTED":
        appointment.status = "REQUESTED"
        if record_lifecycle:
            db.session.add(LifecycleEvent(
                appointment_id=appointment.id,
                from_status="REJECTED",
                to_status="REQUESTED",
                event_type="RETRY_REQUESTED",
                event_time=decision_time,
            ))
        original_status = "REQUESTED"
    facility = appointment.facility
    shipment = appointment.shipment
    if shipment.facility_id != appointment.facility_id:
        return _reject(appointment, "SHIPMENT_FACILITY_MISMATCH", commit, decision_time, record_lifecycle, record_operational_exception=record_operational_exception)
    if shipment.carrier_id != shipment.vehicle.carrier_id:
        return _reject(appointment, "VEHICLE_CARRIER_MISMATCH", commit, decision_time, record_lifecycle, record_operational_exception=record_operational_exception)
    if shipment.direction not in {"INBOUND", "OUTBOUND"}:
        return _reject(appointment, "INVALID_SHIPMENT_DIRECTION", commit, decision_time, record_lifecycle, record_operational_exception=record_operational_exception)
    if shipment.weight_kg < 0:
        return _reject(appointment, "INVALID_SHIPMENT_WEIGHT", commit, decision_time, record_lifecycle, record_operational_exception=record_operational_exception)
    start = appointment.requested_start
    window_end = appointment.requested_end
    end = start + timedelta(minutes=appointment.duration_minutes)
    if window_end <= start or end > window_end:
        return _reject(appointment, "TIME_WINDOW_CONFLICT", commit, decision_time, record_lifecycle, record_operational_exception=record_operational_exception)
    if not _operating_hours(facility, start, end):
        return _reject(appointment, "OUTSIDE_OPERATING_HOURS", commit, decision_time, record_lifecycle, record_operational_exception=record_operational_exception)
    if shipment.weight_kg > shipment.vehicle.capacity_kg:
        return _reject(appointment, "VEHICLE_CAPACITY_EXCEEDED", commit, decision_time, record_lifecycle, record_operational_exception=record_operational_exception)
    requirement = HandlingRequirement.query.filter_by(shipment_id=appointment.shipment_id).first()
    if requirement and (
        requirement.required_workers <= 0 or requirement.service_minutes <= 0
    ):
        return _reject(
            appointment,
            "INVALID_HANDLING_REQUIREMENT",
            commit,
            decision_time,
            record_lifecycle,
            record_operational_exception=record_operational_exception,
        )
    required_workers = requirement.required_workers if requirement else 1
    if commit and db.engine.dialect.name == "mysql":
        facility = Facility.query.filter_by(id=facility.id).with_for_update().one()
    if not yard_available(facility, start, end, exclude_appointment_id=appointment.id):
        return _reject(appointment, "YARD_CAPACITY_EXCEEDED", commit, decision_time, record_lifecycle, record_operational_exception=record_operational_exception)
    shift = available_labor_shift(
        facility,
        start,
        end,
        required_workers=required_workers,
        exclude_appointment_id=appointment.id,
    )
    if shift is None:
        return _reject(appointment, "LABOR_UNAVAILABLE", commit, decision_time, record_lifecycle, record_operational_exception=record_operational_exception)
    slot_type = handling_yard_slot_type(requirement)
    yard_slot = available_yard_slot(
        facility,
        slot_type,
        start,
        end,
        exclude_appointment_id=appointment.id,
    )
    if yard_slot is None:
        return _reject(appointment, "YARD_SLOT_UNAVAILABLE", commit, decision_time, record_lifecycle, record_operational_exception=record_operational_exception)
    eligible_docks = []
    for dock in sorted(facility.docks, key=lambda d: d.code):
        if not dock.active or not compatible(dock, appointment):
            continue
        if not handles_requirement(dock.dock_type, requirement):
            continue
        eligible_docks.append(dock)
    if not eligible_docks:
        if requirement and requirement.refrigerated and requirement.hazardous:
            return _reject(
                appointment,
                "HANDLING_REQUIREMENTS_INCOMPATIBLE",
                commit,
                decision_time,
                record_lifecycle,
                record_operational_exception=record_operational_exception,
            )
        return _reject(appointment, "DOCK_INCOMPATIBLE", commit, decision_time, record_lifecycle, record_operational_exception=record_operational_exception)

    for dock in eligible_docks:
        # Lock the dock master row for the transaction. MySQL/InnoDB then
        # serializes competing schedulers before either can commit a conflict.
        # SQLite ignores FOR UPDATE, so SQLite remains suitable for unit tests
        # but is not used as proof of MySQL concurrency behavior.
        dock = Dock.query.filter_by(id=dock.id).with_for_update().one()
        lock_name = _mysql_lock(dock.id) if commit else None
        try:
            conflict = DockReservation.query.filter(
                DockReservation.dock_id == dock.id,
                DockReservation.status == "ACTIVE",
                DockReservation.start_at < end,
                DockReservation.end_at > start,
            ).with_for_update().first()
            if conflict or not available_dock(
                dock,
                start,
                end,
                exclude_appointment_id=appointment.id,
            ):
                continue
            appointment.scheduled_start, appointment.scheduled_end = start, end
            appointment.status = "SCHEDULED"
            reservation = DockReservation(
                dock_id=dock.id,
                appointment_id=appointment.id,
                start_at=start,
                end_at=end,
            )
            db.session.add(YardSlotReservation(
                yard_slot_id=yard_slot.id,
                appointment_id=appointment.id,
                start_at=start,
                end_at=end,
            ))
            labor_assignment = LaborAssignment.query.filter_by(appointment_id=appointment.id).first()
            if labor_assignment:
                labor_assignment.shift_id = shift.id
                labor_assignment.workers = required_workers
            else:
                db.session.add(LaborAssignment(
                    shift_id=shift.id,
                    appointment_id=appointment.id,
                    workers=required_workers,
                ))
            db.session.add(reservation)
            db.session.add(SchedulingDecision(appointment=appointment, decision="ACCEPTED", reason_code="ALLOCATED",
                                              details={"dock_id": dock.id, "start": start.isoformat()}, created_at=decision_time))
            if record_lifecycle:
                db.session.add(LifecycleEvent(
                    appointment_id=appointment.id,
                    from_status=original_status,
                    to_status="SCHEDULED",
                    event_type="SCHEDULING_ACCEPTED",
                    event_time=decision_time,
                ))
            if commit:
                db.session.commit()
            return reservation
        finally:
            # GET_LOCK is connection-scoped and must be released only after the
            # commit. The application path uses commit=True; batch generation
            # continues to use the row lock and releases at its batch commit.
            if lock_name:
                _mysql_unlock(lock_name)
    return _reject(appointment, "DOCK_UNAVAILABLE", commit, decision_time, record_lifecycle, record_operational_exception=record_operational_exception)


def _reject(
    appointment,
    reason,
    commit,
    decision_time=None,
    record_lifecycle=True,
    update_status=True,
    record_operational_exception=True,
):
    previous_status = appointment.status
    if update_status:
        appointment.status = "REJECTED"
    db.session.add(SchedulingDecision(appointment=appointment, decision="REJECTED", reason_code=reason,
                                      details={"explanation": explain(reason)}, created_at=decision_time))
    if record_operational_exception:
        record_scheduling_exception(appointment, reason)
    if update_status and record_lifecycle:
        db.session.add(LifecycleEvent(
            appointment_id=appointment.id,
            from_status=previous_status,
            to_status="REJECTED",
            event_type="SCHEDULING_REJECTED",
            event_time=decision_time,
            notes=reason,
        ))
    if commit:
        db.session.commit()
    return None


def cancel_appointment(appointment):
    if appointment.status not in {"REQUESTED", "SCHEDULED"}:
        raise ValueError(f"Appointment status {appointment.status} cannot be cancelled")
    previous_status = appointment.status
    appointment.status = "CANCELLED"
    for reservation in DockReservation.query.filter_by(appointment_id=appointment.id, status="ACTIVE"):
        reservation.status = "CANCELLED"
    for reservation in YardSlotReservation.query.filter_by(appointment_id=appointment.id, status="ACTIVE"):
        reservation.status = "CANCELLED"
    for assignment in LaborAssignment.query.filter_by(appointment_id=appointment.id):
        db.session.delete(assignment)
    db.session.add(LifecycleEvent(
        appointment_id=appointment.id,
        from_status=previous_status,
        to_status="CANCELLED",
        event_type="CANCELLED",
    ))
    db.session.commit()


def reschedule_appointment(appointment, requested_start, requested_end=None):
    """Release the old reservation and allocate a new slot atomically."""
    if appointment.status not in {"SCHEDULED", "REQUESTED", "REJECTED"}:
        raise ValueError("Only requested, rejected, or scheduled appointments can be rescheduled")
    requested_end = requested_end or appointment.requested_end
    previous_status = appointment.status
    for reservation in DockReservation.query.filter_by(appointment_id=appointment.id, status="ACTIVE"):
        reservation.status = "CANCELLED"
    for reservation in YardSlotReservation.query.filter_by(appointment_id=appointment.id, status="ACTIVE"):
        reservation.status = "CANCELLED"
    appointment.requested_start = requested_start
    appointment.requested_end = requested_end
    appointment.status = "REQUESTED"
    db.session.add(LifecycleEvent(
        appointment_id=appointment.id,
        from_status=previous_status,
        to_status="REQUESTED",
        event_type="RESCHEDULED",
    ))
    db.session.flush()
    result = schedule_appointment(appointment, commit=False)
    db.session.commit()
    return result
