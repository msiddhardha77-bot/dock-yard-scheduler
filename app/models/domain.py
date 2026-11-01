from datetime import datetime, timezone

from app import db


def utcnow():
    return datetime.now(timezone.utc)


class YardSlot(db.Model):
    __tablename__ = "yard_slots"
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey("facilities.id"), nullable=False, index=True)
    code = db.Column(db.String(40), nullable=False)
    capacity = db.Column(db.Integer, nullable=False, default=1)
    slot_type = db.Column(db.String(30), nullable=False, default="GENERAL")
    active = db.Column(db.Boolean, nullable=False, default=True)
    facility = db.relationship("Facility", back_populates="yard_slots")
    reservations = db.relationship("YardSlotReservation", back_populates="yard_slot")
    __table_args__ = (
        db.UniqueConstraint("facility_id", "code", name="uq_yard_slot_facility_code"),
        db.CheckConstraint("capacity > 0", name="ck_yard_slot_capacity"),
    )


class HandlingRequirement(db.Model):
    __tablename__ = "handling_requirements"
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id"), nullable=False, unique=True, index=True)
    refrigerated = db.Column(db.Boolean, nullable=False, default=False)
    hazardous = db.Column(db.Boolean, nullable=False, default=False)
    required_workers = db.Column(db.Integer, nullable=False, default=1)
    service_minutes = db.Column(db.Integer, nullable=False, default=60)
    shipment = db.relationship("Shipment", back_populates="handling_requirement")
    __table_args__ = (
        db.CheckConstraint("required_workers > 0", name="ck_handling_required_workers"),
        db.CheckConstraint("service_minutes > 0", name="ck_handling_service_minutes"),
    )


class CheckInEvent(db.Model):
    __tablename__ = "check_in_events"
    id = db.Column(db.Integer, primary_key=True)
    event_reference = db.Column(db.String(60), unique=True, nullable=False)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=False, index=True)
    attempt_number = db.Column(db.Integer, nullable=False, default=1)
    attempted_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    outcome = db.Column(db.String(30), nullable=False)
    reason_code = db.Column(db.String(60))
    appointment = db.relationship("Appointment", back_populates="check_in_events")
    __table_args__ = (
        db.UniqueConstraint("appointment_id", "attempt_number", name="uq_checkin_attempt"),
        db.CheckConstraint("attempt_number > 0", name="ck_checkin_attempt_number"),
        db.CheckConstraint(
            "outcome IN ('ACCEPTED', 'REJECTED')",
            name="ck_checkin_outcome",
        ),
    )


class YardSlotReservation(db.Model):
    __tablename__ = "yard_slot_reservations"
    id = db.Column(db.Integer, primary_key=True)
    yard_slot_id = db.Column(db.Integer, db.ForeignKey("yard_slots.id"), nullable=False, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=False, index=True)
    start_at = db.Column(db.DateTime(timezone=True), nullable=False)
    end_at = db.Column(db.DateTime(timezone=True), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="ACTIVE")
    yard_slot = db.relationship("YardSlot", back_populates="reservations")
    appointment = db.relationship("Appointment", back_populates="yard_slot_reservations")
    __table_args__ = (
        db.CheckConstraint("end_at > start_at", name="ck_yard_slot_reservation_time"),
        db.CheckConstraint(
            "status IN ('ACTIVE', 'CANCELLED', 'COMPLETED')",
            name="ck_yard_slot_reservation_status",
        ),
    )


class AppointmentTimeline(db.Model):
    __tablename__ = "appointment_timelines"
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), unique=True, nullable=False)
    actual_arrival_at = db.Column(db.DateTime(timezone=True))
    yard_entry_at = db.Column(db.DateTime(timezone=True))
    dock_arrival_at = db.Column(db.DateTime(timezone=True))
    service_start_at = db.Column(db.DateTime(timezone=True))
    service_end_at = db.Column(db.DateTime(timezone=True))
    departure_at = db.Column(db.DateTime(timezone=True))
    appointment = db.relationship("Appointment", back_populates="timeline")
