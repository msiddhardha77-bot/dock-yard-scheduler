from datetime import datetime, timezone

from app import db
from app.models.events import OperationalException
from app.models.events import LifecycleEvent
from app.models.domain import YardSlotReservation
from app.models.masters import LaborAssignment
from app.models.scheduling import DockReservation


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def detect_arrival(appointment, actual_time):
    if not appointment.scheduled_start:
        return None
    delta = (_utc(actual_time) - _utc(appointment.scheduled_start)).total_seconds() / 60
    if delta > 15:
        item = OperationalException(appointment_id=appointment.id, facility_id=appointment.facility_id,
                                    severity="WARNING", cause_code="LATE_ARRIVAL",
                                    description=f"Arrival was {round(delta)} minutes late")
        db.session.add(item); db.session.commit(); return item
    if delta < -30:
        item = OperationalException(appointment_id=appointment.id, facility_id=appointment.facility_id,
                                    severity="INFO", cause_code="EARLY_ARRIVAL", description="Truck arrived early")
        db.session.add(item); db.session.commit(); return item
    return None


def detect_no_show(appointment, now=None):
    """Mark a scheduled appointment as no-show after its window closes."""
    now = now or datetime.now(timezone.utc)
    if appointment.status == "SCHEDULED" and _utc(appointment.requested_end) < _utc(now):
        appointment.status = "NO_SHOW"
        db.session.add(LifecycleEvent(
            appointment_id=appointment.id,
            from_status="SCHEDULED",
            to_status="NO_SHOW",
            event_type="NO_SHOW_DETECTED",
            event_time=now,
        ))
        for reservation in DockReservation.query.filter_by(appointment_id=appointment.id, status="ACTIVE"):
            reservation.status = "CANCELLED"
        for reservation in YardSlotReservation.query.filter_by(appointment_id=appointment.id, status="ACTIVE"):
            reservation.status = "CANCELLED"
        for assignment in LaborAssignment.query.filter_by(appointment_id=appointment.id):
            db.session.delete(assignment)
        item = OperationalException(appointment_id=appointment.id, facility_id=appointment.facility_id,
                                    severity="WARNING", cause_code="NO_SHOW",
                                    description="Appointment window closed without gate check-in")
        db.session.add(item); db.session.commit()
        return item
    return None
