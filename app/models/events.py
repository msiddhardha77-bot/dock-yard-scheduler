from datetime import datetime, timezone

from app import db


def utcnow():
    return datetime.now(timezone.utc)


class LifecycleEvent(db.Model):
    __tablename__ = "lifecycle_events"
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=False, index=True)
    from_status = db.Column(db.String(20))
    to_status = db.Column(db.String(20), nullable=False)
    event_type = db.Column(db.String(40), nullable=False)
    event_time = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    notes = db.Column(db.Text)
    appointment = db.relationship("Appointment", back_populates="events")


class OperationalException(db.Model):
    __tablename__ = "operational_exceptions"
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), index=True)
    facility_id = db.Column(db.Integer, db.ForeignKey("facilities.id"), nullable=False, index=True)
    severity = db.Column(db.String(20), nullable=False)
    cause_code = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    detected_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at = db.Column(db.DateTime(timezone=True))
    resolution_notes = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="OPEN", index=True)


class SimulationRun(db.Model):
    __tablename__ = "simulation_runs"
    id = db.Column(db.Integer, primary_key=True)
    seed = db.Column(db.Integer, nullable=False)
    mode = db.Column(db.String(20), nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at = db.Column(db.DateTime(timezone=True))
    manifest = db.Column(db.JSON, default=dict)


class AnomalyLabel(db.Model):
    __tablename__ = "anomaly_labels"
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=False)
    label = db.Column(db.String(50), nullable=False)
    source = db.Column(db.String(30), nullable=False, default="synthetic_ground_truth")


class GroundTruthRecord(db.Model):
    __tablename__ = "ground_truth_records"
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    truth = db.Column(db.JSON, nullable=False)
