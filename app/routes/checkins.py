from datetime import datetime, timezone
from flask import Blueprint, flash, redirect, render_template, url_for
from app import db
from app.models.operations import Appointment, GateVisit
from app.models.domain import AppointmentTimeline, CheckInEvent
from app.services.exception_detector import detect_arrival
from app.services.lifecycle import transition
from app.models.operations import YardOccupancy
from app.models.scheduling import DockReservation
from app.models.domain import YardSlotReservation
from app.models.masters import LaborAssignment
from app.services.lifecycle import display_status

checkins_bp = Blueprint("checkins", __name__)


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

@checkins_bp.get("/")
def index():
    appointments = Appointment.query.filter(
        Appointment.status.in_(["SCHEDULED", "CHECKED_IN", "AT_DOCK", "IN_SERVICE", "COMPLETED"])
    ).order_by(Appointment.scheduled_start, Appointment.id).limit(100).all()
    appointment_ids = [appointment.id for appointment in appointments]
    gate_visits = {
        visit.appointment_id: visit
        for visit in GateVisit.query.filter(GateVisit.appointment_id.in_(appointment_ids)).all()
    } if appointment_ids else {}
    timelines = {
        timeline.appointment_id: timeline
        for timeline in AppointmentTimeline.query.filter(AppointmentTimeline.appointment_id.in_(appointment_ids)).all()
    } if appointment_ids else {}
    work_durations = {
        appointment_id: (timeline.service_end_at - timeline.service_start_at).total_seconds() / 60
        for appointment_id, timeline in timelines.items()
        if timeline.service_start_at and timeline.service_end_at
    }
    return render_template(
        "checkin.html",
        appointments=appointments,
        gate_visits=gate_visits,
        timelines=timelines,
        work_durations=work_durations,
        display_status=display_status,
    )

@checkins_bp.post("/<int:appointment_id>")
def checkin(appointment_id):
    appointment = db.get_or_404(Appointment, appointment_id); now = datetime.now(timezone.utc)
    if appointment.status != "SCHEDULED":
        attempt_number = CheckInEvent.query.filter_by(appointment_id=appointment.id).count() + 1
        db.session.add(CheckInEvent(
            event_reference=f"CHECK-{appointment.id}-{attempt_number:02d}",
            appointment_id=appointment.id,
            attempt_number=attempt_number,
            outcome="REJECTED",
            reason_code="APPOINTMENT_NOT_SCHEDULED",
            attempted_at=now,
        ))
        db.session.commit()
        flash("Check-in rejected: appointment is not scheduled.", "danger")
        return redirect(url_for("checkins.index"))
    if appointment.scheduled_start and now < _utc(appointment.scheduled_start):
        attempt_number = CheckInEvent.query.filter_by(appointment_id=appointment.id).count() + 1
        attempt = CheckInEvent(event_reference=f"CHECK-{appointment.id}-{attempt_number:02d}", appointment_id=appointment.id, attempt_number=attempt_number, outcome="REJECTED", reason_code="EARLY_CHECK_IN", attempted_at=now)
        db.session.add(attempt); db.session.commit()
        flash("Check-in rejected: arrival is before the permitted appointment time.", "danger")
        return redirect(url_for("checkins.index"))
    attempt_number = CheckInEvent.query.filter_by(appointment_id=appointment.id).count() + 1
    attempt = CheckInEvent(event_reference=f"CHECK-{appointment.id}-{attempt_number:02d}", appointment_id=appointment.id, attempt_number=attempt_number, outcome="ACCEPTED", attempted_at=now)
    db.session.add(attempt)
    db.session.add(GateVisit(appointment_id=appointment.id, check_in_at=now))
    db.session.add(YardOccupancy(facility_id=appointment.facility_id, appointment_id=appointment.id, entered_at=now))
    timeline = AppointmentTimeline.query.filter_by(appointment_id=appointment.id).first()
    if timeline is None:
        timeline = AppointmentTimeline(appointment_id=appointment.id)
        db.session.add(timeline)
    timeline.actual_arrival_at = now
    timeline.yard_entry_at = now
    detect_arrival(appointment, now)
    transition(appointment, "CHECKED_IN", "GATE_CHECK_IN", now); flash("Truck checked in.", "success")
    return redirect(url_for("checkins.index"))


@checkins_bp.post("/<int:appointment_id>/checkout")
def checkout(appointment_id):
    appointment = db.get_or_404(Appointment, appointment_id); now = datetime.now(timezone.utc)
    visit = GateVisit.query.filter_by(appointment_id=appointment.id).first()
    if not visit:
        flash("Cannot check out before check-in.", "danger")
        return redirect(url_for("checkins.index"))
    if appointment.status != "COMPLETED":
        flash("Appointment must be completed before checkout.", "danger")
        return redirect(url_for("checkins.index"))
    visit.check_out_at = now
    occupancy = YardOccupancy.query.filter_by(appointment_id=appointment.id, exited_at=None).first()
    if occupancy:
        occupancy.exited_at = now
    timeline = AppointmentTimeline.query.filter_by(appointment_id=appointment.id).first()
    if timeline:
        timeline.departure_at = now
    for reservation in DockReservation.query.filter_by(appointment_id=appointment.id, status="ACTIVE"):
        reservation.status = "COMPLETED"
    for reservation in YardSlotReservation.query.filter_by(appointment_id=appointment.id, status="ACTIVE"):
        reservation.status = "COMPLETED"
    for assignment in LaborAssignment.query.filter_by(appointment_id=appointment.id):
        db.session.delete(assignment)
    transition(appointment, "DEPARTED", "GATE_CHECK_OUT", now)
    flash("Truck checked out.", "success")
    return redirect(url_for("checkins.index"))


@checkins_bp.post("/<int:appointment_id>/complete")
def complete(appointment_id):
    appointment = db.get_or_404(Appointment, appointment_id)
    try:
        now = datetime.now(timezone.utc)
        timeline = AppointmentTimeline.query.filter_by(appointment_id=appointment.id).first()
        if timeline is None:
            timeline = AppointmentTimeline(appointment_id=appointment.id)
            db.session.add(timeline)
        if appointment.status == "CHECKED_IN":
            timeline.dock_arrival_at = now
            transition(appointment, "AT_DOCK", "DOCK_ASSIGNMENT", now)
        elif appointment.status == "AT_DOCK":
            timeline.service_start_at = now
            transition(appointment, "IN_SERVICE", "SERVICE_START", now)
        elif appointment.status == "IN_SERVICE":
            timeline.service_end_at = now
            transition(appointment, "COMPLETED", "SERVICE_COMPLETE", now)
        else:
            flash("Appointment is not ready to advance through service.", "danger")
            return redirect(url_for("checkins.index"))
        flash("Service state advanced.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("checkins.index"))
