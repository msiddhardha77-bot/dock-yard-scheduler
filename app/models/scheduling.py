from datetime import datetime, timezone

from app import db


def utcnow():
    return datetime.now(timezone.utc)


class DockReservation(db.Model):
    __tablename__ = "dock_reservations"
    id = db.Column(db.Integer, primary_key=True)
    dock_id = db.Column(db.Integer, db.ForeignKey("docks.id"), nullable=False, index=True)
    # Historical reservations remain queryable after cancellation/rescheduling;
    # only ACTIVE rows participate in overlap checks.
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=False, index=True)
    start_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    end_at = db.Column(db.DateTime(timezone=True), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="ACTIVE", index=True)
    dock = db.relationship("Dock", back_populates="reservations")
    appointment = db.relationship("Appointment", back_populates="dock_reservations")
    __table_args__ = (
        db.CheckConstraint("end_at > start_at", name="ck_reservation_time_order"),
        db.CheckConstraint(
            "status IN ('ACTIVE', 'CANCELLED', 'COMPLETED')",
            name="ck_dock_reservation_status",
        ),
    )


class SchedulingDecision(db.Model):
    __tablename__ = "scheduling_decisions"
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=False, index=True)
    decision = db.Column(db.String(20), nullable=False)
    reason_code = db.Column(db.String(60), nullable=False)
    details = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    appointment = db.relationship("Appointment")
