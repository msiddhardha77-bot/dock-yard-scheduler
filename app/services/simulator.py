from datetime import timedelta
from random import Random


def service_duration(base_minutes=60, seed=42):
    """Return a deterministic, bounded operational duration for simulation."""
    return max(15, base_minutes + Random(seed).randint(-15, 30))


def simulated_completion(start_at, base_minutes=60, seed=42):
    return start_at + timedelta(minutes=service_duration(base_minutes, seed))


def simulate_appointments(seed=20261022):
    """Project deterministic service durations without writing database rows."""
    from app.models.events import OperationalException
    from app.models.operations import Appointment
    from app.models.scheduling import SchedulingDecision

    appointments = Appointment.query.order_by(Appointment.id).all()
    scheduled = [
        appointment for appointment in appointments
        if appointment.status in {"SCHEDULED", "CHECKED_IN", "AT_DOCK", "IN_SERVICE"}
        and appointment.scheduled_start is not None
    ]
    projections = []
    for appointment in scheduled:
        projected_minutes = service_duration(appointment.duration_minutes, seed + appointment.id)
        projected_end = appointment.scheduled_start + timedelta(minutes=projected_minutes)
        projections.append({
            "appointment_id": appointment.id,
            "projected_service_minutes": projected_minutes,
            "within_requested_window": projected_end <= appointment.requested_end,
        })

    rejected = Appointment.query.filter_by(status="REJECTED").count()
    rejected_decisions = SchedulingDecision.query.filter_by(decision="REJECTED").all()
    rejection_reasons = {}
    for decision in rejected_decisions:
        rejection_reasons[decision.reason_code] = rejection_reasons.get(decision.reason_code, 0) + 1

    total_minutes = sum(row["projected_service_minutes"] for row in projections)
    on_time = sum(row["within_requested_window"] for row in projections)
    return {
        "seed": seed,
        "appointment_count": len(appointments),
        "scheduled_count": sum(appointment.status == "SCHEDULED" for appointment in appointments),
        "projection_count": len(projections),
        "rejected_count": rejected,
        "projected_service_minutes": total_minutes,
        "average_projected_service_minutes": round(total_minutes / len(projections), 2) if projections else None,
        "within_window_count": on_time,
        "projected_late_count": len(projections) - on_time,
        "projected_on_time_rate_percent": round(on_time / len(projections) * 100, 2) if projections else None,
        "rejection_reasons": rejection_reasons,
        "open_exception_count": OperationalException.query.filter_by(status="OPEN").count(),
    }

