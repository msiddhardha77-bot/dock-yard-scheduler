from datetime import datetime, timezone

from app import db


def utcnow():
    return datetime.now(timezone.utc)


class Shipment(db.Model):
    __tablename__ = "shipments"
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(50), unique=True, nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey("facilities.id"), nullable=False)
    carrier_id = db.Column(db.Integer, db.ForeignKey("carriers.id"), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=False)
    direction = db.Column(db.String(10), nullable=False)
    weight_kg = db.Column(db.Integer, nullable=False)
    facility = db.relationship("Facility")
    vehicle = db.relationship("Vehicle")
    handling_requirement = db.relationship(
        "HandlingRequirement",
        back_populates="shipment",
        uselist=False,
    )
    appointments = db.relationship("Appointment", back_populates="shipment")
    __table_args__ = (
        db.CheckConstraint(
            "direction IN ('INBOUND', 'OUTBOUND')",
            name="ck_shipment_direction",
        ),
        db.CheckConstraint("weight_kg >= 0", name="ck_shipment_weight_nonnegative"),
    )


class Appointment(db.Model):
    __tablename__ = "appointments"
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(50), unique=True, nullable=False)
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id"), nullable=False, index=True)
    facility_id = db.Column(db.Integer, db.ForeignKey("facilities.id"), nullable=False, index=True)
    requested_start = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    requested_end = db.Column(db.DateTime(timezone=True), nullable=False)
    scheduled_start = db.Column(db.DateTime(timezone=True))
    scheduled_end = db.Column(db.DateTime(timezone=True))
    duration_minutes = db.Column(db.Integer, nullable=False, default=60)
    status = db.Column(db.String(20), nullable=False, default="REQUESTED", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    shipment = db.relationship("Shipment", back_populates="appointments")
    facility = db.relationship("Facility")
    events = db.relationship("LifecycleEvent", back_populates="appointment", order_by="LifecycleEvent.event_time")
    dock_reservations = db.relationship("DockReservation", back_populates="appointment")
    yard_slot_reservations = db.relationship(
        "YardSlotReservation",
        back_populates="appointment",
    )
    check_in_events = db.relationship("CheckInEvent", back_populates="appointment")
    timeline = db.relationship(
        "AppointmentTimeline",
        back_populates="appointment",
        uselist=False,
    )
    __table_args__ = (
        db.CheckConstraint("requested_end > requested_start", name="ck_appointment_requested_window"),
        db.CheckConstraint("duration_minutes > 0", name="ck_appointment_duration_positive"),
        db.CheckConstraint(
            "status IN ('REQUESTED', 'SCHEDULED', 'CHECKED_IN', 'AT_DOCK', "
            "'IN_SERVICE', 'COMPLETED', 'DEPARTED', 'CANCELLED', 'REJECTED', 'NO_SHOW')",
            name="ck_appointment_status",
        ),
    )


class YardOccupancy(db.Model):
    __tablename__ = "yard_occupancy"
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey("facilities.id"), nullable=False, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=False)
    entered_at = db.Column(db.DateTime(timezone=True), nullable=False)
    exited_at = db.Column(db.DateTime(timezone=True))
    __table_args__ = (
        db.CheckConstraint(
            "exited_at IS NULL OR exited_at >= entered_at",
            name="ck_yard_occupancy_time_order",
        ),
    )


class GateVisit(db.Model):
    __tablename__ = "gate_visits"
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), unique=True, nullable=False)
    check_in_at = db.Column(db.DateTime(timezone=True), nullable=False)
    check_out_at = db.Column(db.DateTime(timezone=True))
    appointment = db.relationship("Appointment")
