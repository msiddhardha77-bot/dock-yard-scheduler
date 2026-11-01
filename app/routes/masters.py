from flask import Blueprint, render_template
from app.models.masters import Facility

masters_bp = Blueprint("masters", __name__)

@masters_bp.get("/")
def index(): return render_template("masters.html", facilities=Facility.query.order_by(Facility.code).all())

