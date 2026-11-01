from datetime import datetime, timezone

from app import db
from app.models.events import LifecycleEvent

TRANSITIONS = {
    "REQUESTED": {"SCHEDULED", "REJECTED", "CANCELLED"},
    "SCHEDULED": {"REQUESTED", "CHECKED_IN", "CANCELLED", "NO_SHOW"},
    "CHECKED_IN": {"AT_DOCK", "CANCELLED"},
    "AT_DOCK": {"IN_SERVICE"},
    "IN_SERVICE": {"COMPLETED"},
    "COMPLETED": {"DEPARTED"},
    "DEPARTED": set(),
    "REJECTED": {"REQUESTED"},
    "CANCELLED": set(),
    "NO_SHOW": set(),
}

STATUS_LABELS = {
    "SCHEDULED": "Scheduled",
    "CHECKED_IN": "Checked In",
    "AT_DOCK": "Docked",
    "IN_SERVICE": "In Service",
    "COMPLETED": "Service Completed",
    "DEPARTED": "Checked Out",
}


def display_status(status):
    return STATUS_LABELS.get(status, status.replace("_", " ").title())


def allowed_transition(current, target):
    return target in TRANSITIONS.get(current, set())


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def transition(appointment, to_status, event_type=None, when=None, notes=None):
    if to_status not in TRANSITIONS.get(appointment.status, set()):
        raise ValueError(f"Invalid transition {appointment.status} -> {to_status}")
    event_time = when or datetime.now(timezone.utc)
    latest = (
        LifecycleEvent.query.filter_by(appointment_id=appointment.id)
        .order_by(LifecycleEvent.event_time.desc(), LifecycleEvent.id.desc())
        .first()
    )
    if latest and _utc(event_time) < _utc(latest.event_time):
        raise ValueError("Lifecycle event time cannot precede the previous event")
    old = appointment.status
    appointment.status = to_status
    db.session.add(LifecycleEvent(appointment=appointment, from_status=old, to_status=to_status,
                                  event_type=event_type or to_status, event_time=event_time, notes=notes))
    db.session.commit()
    return appointment
