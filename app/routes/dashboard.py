from flask import Blueprint, render_template
from app.services.metrics import appointment_status_counts, dashboard_metrics

dashboard_bp = Blueprint("dashboard", __name__)

@dashboard_bp.get("/")
@dashboard_bp.get("/dashboard")
def index():
    return render_template(
        "dashboard.html",
        metrics=dashboard_metrics(),
        status_counts=appointment_status_counts(),
    )
