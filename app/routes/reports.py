import csv
from io import StringIO

from flask import Blueprint, Response, render_template, request

from app.services.metrics import (
    appointment_status_counts,
    dashboard_metrics,
    evaluation_metrics,
    timeline_metrics,
    labor_utilization_metrics,
)
from app.services.simulator import simulate_appointments


reports_bp = Blueprint("reports", __name__)


@reports_bp.get("/")
def index():
    return render_template(
        "reports.html",
        metrics=dashboard_metrics(),
        evaluation=evaluation_metrics(),
        timeline=timeline_metrics(),
        labor=labor_utilization_metrics(),
        status_counts=appointment_status_counts(),
    )


@reports_bp.get("/appointments.csv")
def appointments_csv():
    from app.models.operations import Appointment

    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(["reference", "status", "requested_start"])

    for appointment in Appointment.query.order_by(Appointment.id):
        writer.writerow([
            appointment.reference,
            appointment.status,
            appointment.requested_start.isoformat(),
        ])

    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=appointments.csv"
        },
    )


@reports_bp.get("/simulation")
def simulation():
    seed = request.args.get("seed", default=20261022, type=int)
    result = simulate_appointments(seed)

    return render_template("simulation.html", result=result)