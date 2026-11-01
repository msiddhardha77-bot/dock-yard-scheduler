from datetime import datetime, time, timezone

from app import db


def utcnow():
    return datetime.now(timezone.utc)


class Facility(db.Model):
    __tablename__ = "facilities"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    timezone = db.Column(db.String(64), nullable=False, default="UTC")
    operating_start = db.Column(db.Time, nullable=False, default=time(6))
    operating_end = db.Column(db.Time, nullable=False, default=time(22))
    yard_capacity = db.Column(db.Integer, nullable=False, default=100)
    active = db.Column(db.Boolean, nullable=False, default=True)
    docks = db.relationship("Dock", back_populates="facility", cascade="all, delete-orphan")
    zones = db.relationship("YardZone", back_populates="facility", cascade="all, delete-orphan")
    yard_slots = db.relationship("YardSlot", back_populates="facility")
    labor_shifts = db.relationship("LaborShift", back_populates="facility")
    __table_args__ = (
        db.CheckConstraint("yard_capacity >= 0", name="ck_facility_yard_capacity"),
    )


class Dock(db.Model):
    __tablename__ = "docks"
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey("facilities.id"), nullable=False, index=True)
    code = db.Column(db.String(30), nullable=False)
    dock_type = db.Column(db.String(30), nullable=False, default="GENERAL")
    supports_inbound = db.Column(db.Boolean, nullable=False, default=True)
    supports_outbound = db.Column(db.Boolean, nullable=False, default=True)
    vehicle_types = db.Column(db.String(255), nullable=False, default="VAN,TRUCK,TRAILER")
    active = db.Column(db.Boolean, nullable=False, default=True)
    facility = db.relationship("Facility", back_populates="docks")
    reservations = db.relationship("DockReservation", back_populates="dock")
    __table_args__ = (db.UniqueConstraint("facility_id", "code", name="uq_dock_facility_code"),)

    def supports(self, direction, vehicle_type):
        return ((direction == "INBOUND" and self.supports_inbound) or
                (direction == "OUTBOUND" and self.supports_outbound)) and vehicle_type in self.vehicle_types.split(",")


class YardZone(db.Model):
    __tablename__ = "yard_zones"
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey("facilities.id"), nullable=False)
    code = db.Column(db.String(30), nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    facility = db.relationship("Facility", back_populates="zones")
    __table_args__ = (db.UniqueConstraint("facility_id", "code", name="uq_zone_facility_code"),)


class Carrier(db.Model):
    __tablename__ = "carriers"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)


class Driver(db.Model):
    __tablename__ = "drivers"
    id = db.Column(db.Integer, primary_key=True)
    carrier_id = db.Column(db.Integer, db.ForeignKey("carriers.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    license_number = db.Column(db.String(50), unique=True, nullable=False)
    carrier = db.relationship("Carrier")


class Vehicle(db.Model):
    __tablename__ = "vehicles"
    id = db.Column(db.Integer, primary_key=True)
    carrier_id = db.Column(db.Integer, db.ForeignKey("carriers.id"), nullable=False)
    registration = db.Column(db.String(30), unique=True, nullable=False)
    vehicle_type = db.Column(db.String(30), nullable=False)
    capacity_kg = db.Column(db.Integer, nullable=False, default=10000)
    carrier = db.relationship("Carrier")


class LaborShift(db.Model):
    __tablename__ = "labor_shifts"
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey("facilities.id"), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    workers = db.Column(db.Integer, nullable=False)
    facility = db.relationship("Facility", back_populates="labor_shifts")
    __table_args__ = (
        db.CheckConstraint("workers >= 0", name="ck_labor_shift_workers"),
    )


class LaborAssignment(db.Model):
    __tablename__ = "labor_assignments"
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, db.ForeignKey("labor_shifts.id"), nullable=False, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=False, index=True)
    workers = db.Column(db.Integer, nullable=False, default=1)
    shift = db.relationship("LaborShift")
    appointment = db.relationship("Appointment")
    __table_args__ = (
        db.UniqueConstraint("appointment_id", name="uq_labor_assignment_appointment"),
        db.CheckConstraint("workers > 0", name="ck_labor_assignment_workers"),
    )
