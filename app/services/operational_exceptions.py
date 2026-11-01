from app import db
from app.models.events import OperationalException


SCHEDULING_EXCEPTION_MAP = {
    "DOCK_UNAVAILABLE": ("PEAK_CONGESTION", "WARNING"),
    "YARD_CAPACITY_EXCEEDED": ("PEAK_CONGESTION", "WARNING"),
    "YARD_SLOT_UNAVAILABLE": ("PEAK_CONGESTION", "WARNING"),
    "DOCK_INCOMPATIBLE": ("INCOMPATIBLE_LOAD", "WARNING"),
    "HANDLING_REQUIREMENTS_INCOMPATIBLE": ("INCOMPATIBLE_LOAD", "WARNING"),
    "VEHICLE_INCOMPATIBLE": ("INCOMPATIBLE_LOAD", "WARNING"),
    "VEHICLE_CAPACITY_EXCEEDED": ("INCOMPATIBLE_LOAD", "WARNING"),
    "LABOR_UNAVAILABLE": ("LABOR_UNAVAILABLE", "WARNING"),
    "INVALID_STATUS": ("INVALID_SCHEDULING_DECISION", "WARNING"),
}


def record_scheduling_exception(appointment, reason_code):
    """Record one operational scheduling exception for a failed attempt.

    Ground-truth anomaly labels and generator runs do not call this path.
    Repeated attempts for the same appointment/cause reuse the existing row,
    preventing duplicate operational exceptions.
    """
    mapping = SCHEDULING_EXCEPTION_MAP.get(reason_code)
    if mapping is None:
        return None
    cause_code, severity = mapping
    existing = OperationalException.query.filter_by(
        appointment_id=appointment.id,
        cause_code=cause_code,
    ).order_by(OperationalException.id).first()
    if existing:
        return existing
    item = OperationalException(
        appointment_id=appointment.id,
        facility_id=appointment.facility_id,
        severity=severity,
        cause_code=cause_code,
        description=f"Scheduling failure: {reason_code}",
    )
    db.session.add(item)
    return item
