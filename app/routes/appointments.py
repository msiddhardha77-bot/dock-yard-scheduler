from datetime import datetime, timezone
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError
from app import db
from app.models.masters import Facility
from app.models.operations import Appointment, GateVisit, Shipment
from app.models.scheduling import DockReservation, SchedulingDecision
from app.models.domain import YardSlotReservation
from app.services.scheduler import cancel_appointment, reschedule_appointment, schedule_appointment
from app.services.reason_codes import explain
from app.services.lifecycle import display_status
from app.models.domain import AppointmentTimeline

appointments_bp = Blueprint("appointments", __name__)

@appointments_bp.get("/")
def list_appointments():
    page = request.args.get("page", 1, type=int)
    query = Appointment.query.order_by(Appointment.requested_start.desc())
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    facility_id = request.args.get("facility_id", type=int)
    if facility_id:
        query = query.filter_by(facility_id=facility_id)
    direction = request.args.get("direction", "").upper()
    if direction in {"INBOUND", "OUTBOUND"}:
        query = query.join(Appointment.shipment).filter(Shipment.direction == direction)
    return render_template(
        "appointments.html",
        appointments=query.paginate(page=page, per_page=25, error_out=False),
        facilities=Facility.query.order_by(Facility.code).all(),
        selected_status=request.args.get("status", ""),
        selected_facility=facility_id,
        selected_direction=direction,
    )


def _parse_datetime(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@appointments_bp.route("/new", methods=["GET", "POST"])
def create():
    facilities = Facility.query.order_by(Facility.code).all()
    if request.method == "POST":
        try:
            facility_id = int(request.form["facility_id"])
            start = _parse_datetime(request.form["requested_start"])
            end = _parse_datetime(request.form["requested_end"])
            shipment = Shipment.query.filter_by(reference=request.form["shipment_reference"]).first()
            if not shipment:
                raise ValueError("Shipment reference was not found")
            facility = db.session.get(Facility, facility_id)
            if facility is None or not facility.active:
                raise ValueError("An active facility must be selected")
            if shipment.facility_id != facility_id:
                raise ValueError("Appointment facility must match the shipment facility")
            if end <= start:
                raise ValueError("Requested end must be after requested start")
            appointment = Appointment(reference=request.form["reference"], shipment_id=shipment.id, facility_id=facility_id,
                                      requested_start=start, requested_end=end, duration_minutes=int(request.form.get("duration_minutes", 60)))
            db.session.add(appointment); db.session.flush()
            schedule_appointment(appointment)
            decision = SchedulingDecision.query.filter_by(appointment_id=appointment.id).order_by(SchedulingDecision.id.desc()).first()
            if appointment.status == "SCHEDULED":
                flash(f"Appointment {appointment.reference} scheduled.", "success")
            else:
                code = decision.reason_code if decision else "DOCK_UNAVAILABLE"
                flash(f"Appointment {appointment.reference} rejected: {explain(code)} ({code})", "danger")
            return redirect(url_for("appointments.list_appointments"))
        except (KeyError, ValueError) as exc:
            db.session.rollback(); flash(str(exc), "danger")
        except IntegrityError:
            db.session.rollback(); flash("Appointment reference already exists or the submission conflicts with stored data.", "danger")
    return render_template("appointment_detail.html", appointment=None, facilities=facilities, create_mode=True)


@appointments_bp.get("/<int:appointment_id>")
def detail(appointment_id):
    appointment = db.get_or_404(Appointment, appointment_id)
    decisions = SchedulingDecision.query.filter_by(appointment_id=appointment.id).order_by(SchedulingDecision.id.desc()).all()
    dock_reservations = DockReservation.query.filter_by(appointment_id=appointment.id).order_by(DockReservation.id.desc()).all()
    yard_reservations = YardSlotReservation.query.filter_by(appointment_id=appointment.id).order_by(YardSlotReservation.id.desc()).all()
    timeline = AppointmentTimeline.query.filter_by(appointment_id=appointment.id).first()
    gate_visit = GateVisit.query.filter_by(appointment_id=appointment.id).first()
    work_duration_minutes = (
        (timeline.service_end_at - timeline.service_start_at).total_seconds() / 60
        if timeline and timeline.service_start_at and timeline.service_end_at
        else None
    )
    return render_template(
        "appointment_detail.html",
        appointment=appointment,
        create_mode=False,
        facilities=[],
        decisions=decisions,
        dock_reservations=dock_reservations,
        yard_reservations=yard_reservations,
        timeline=timeline,
        gate_visit=gate_visit,
        work_duration_minutes=work_duration_minutes,
        display_status=display_status,
    )

@appointments_bp.post("/<int:appointment_id>/cancel")
def cancel(appointment_id):
    appointment = db.get_or_404(Appointment, appointment_id)
    try:
        cancel_appointment(appointment)
        flash("Appointment cancelled.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("appointments.list_appointments"))


@appointments_bp.post("/<int:appointment_id>/reschedule")
def reschedule(appointment_id):
    appointment = db.get_or_404(Appointment, appointment_id)
    try:
        start = _parse_datetime(request.form["requested_start"])
        end = _parse_datetime(request.form["requested_end"])
        result = reschedule_appointment(appointment, start, end)
        if result:
            flash("Appointment rescheduled.", "success")
        else:
            decision = SchedulingDecision.query.filter_by(appointment_id=appointment.id).order_by(SchedulingDecision.id.desc()).first()
            code = decision.reason_code if decision else "DOCK_UNAVAILABLE"
            flash(f"Reschedule rejected: {explain(code)} ({code})", "danger")
    except (KeyError, ValueError) as exc:
        db.session.rollback(); flash(str(exc), "danger")
    except IntegrityError:
        db.session.rollback(); flash("Reschedule conflicts with an existing reservation.", "danger")
    return redirect(url_for("appointments.detail", appointment_id=appointment.id))
