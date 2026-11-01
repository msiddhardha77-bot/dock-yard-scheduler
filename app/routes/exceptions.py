from datetime import datetime, timezone
from flask import Blueprint, flash, redirect, render_template, request, url_for
from app import db
from app.models.events import OperationalException
from app.models.operations import Appointment
from app.services.exception_detector import detect_no_show

exceptions_bp = Blueprint("exceptions", __name__)

@exceptions_bp.get("/")
def index():
    return render_template("exceptions.html", exceptions=OperationalException.query.order_by(OperationalException.detected_at.desc()).limit(200).all())


@exceptions_bp.post("/detect-no-shows")
def detect_no_shows():
    now = datetime.now(timezone.utc)
    overdue = Appointment.query.filter(
        Appointment.status == "SCHEDULED",
        Appointment.requested_end < now,
    ).all()
    detected = sum(detect_no_show(appointment, now) is not None for appointment in overdue)
    flash(f"Detected {detected} no-show appointment(s).", "info")
    return redirect(url_for("exceptions.index"))


@exceptions_bp.post("/<int:exception_id>/resolve")
def resolve(exception_id):
    item = db.get_or_404(OperationalException, exception_id)
    item.status = "RESOLVED"
    item.resolved_at = datetime.now(timezone.utc)
    item.resolution_notes = request.form.get("notes", "Resolved by operations")
    db.session.commit()
    flash("Exception resolved.", "success")
    return redirect(url_for("exceptions.index"))
