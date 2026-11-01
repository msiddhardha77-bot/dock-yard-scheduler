from datetime import datetime, timedelta, timezone, time

from app import db
from app.models.masters import Carrier, Dock, Facility, LaborShift, Vehicle
from app.models.domain import YardSlot
from app.models.events import LifecycleEvent
from app.models.operations import Appointment, Shipment
from app.models.scheduling import SchedulingDecision


def test_appointment_form_detail_filter_reschedule_cancel(app, client):
    with app.app_context():
        facility = Facility(code="F1", name="Test")
        carrier = Carrier(code="C1", name="Carrier")
        db.session.add_all([facility, carrier]); db.session.flush()
        db.session.add_all([Dock(facility_id=facility.id, code="D1"), LaborShift(facility_id=facility.id, name="day", start_time=time(6), end_time=time(22), workers=5), YardSlot(facility_id=facility.id, code="Y1", capacity=5)])
        vehicle = Vehicle(carrier_id=carrier.id, registration="TRK1", vehicle_type="TRUCK")
        db.session.add(vehicle); db.session.flush()
        shipment = Shipment(reference="S1", facility_id=facility.id, carrier_id=carrier.id, vehicle_id=vehicle.id, direction="INBOUND", weight_kg=1000)
        db.session.add(shipment); db.session.commit()
        facility_id = facility.id
    start = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
    response = client.post("/appointments/new", data={
        "reference": "A1", "shipment_reference": "S1", "facility_id": facility_id,
        "requested_start": start.isoformat(timespec="minutes"),
        "requested_end": (start + timedelta(hours=2)).isoformat(timespec="minutes"),
        "duration_minutes": "60",
    })
    assert response.status_code == 302
    with app.app_context():
        appointment = Appointment.query.filter_by(reference="A1").one()
        appointment_id = appointment.id
        initial_events = LifecycleEvent.query.filter_by(appointment_id=appointment_id).all()
        initial_decision = SchedulingDecision.query.filter_by(appointment_id=appointment_id).one()
        assert [(event.from_status, event.to_status) for event in initial_events] == [("REQUESTED", "SCHEDULED")]
        assert initial_decision.decision == "ACCEPTED"
    detail = client.get(f"/appointments/{appointment_id}")
    assert detail.status_code == 200
    assert b"Scheduling decisions" in detail.data
    assert b"Lifecycle history" in detail.data
    assert b"ALLOCATED" in detail.data
    assert client.get("/appointments/?status=SCHEDULED").status_code == 200
    with app.app_context():
        appointment = db.session.get(Appointment, appointment_id)
        appointment.shipment.direction = "OUTBOUND"
        db.session.commit()
    outbound = client.get("/appointments/?direction=OUTBOUND")
    inbound = client.get("/appointments/?direction=INBOUND")
    assert outbound.status_code == inbound.status_code == 200
    assert b"A1" in outbound.data
    assert b"A1" not in inbound.data
    moved = start.replace(hour=11)
    assert client.post(f"/appointments/{appointment_id}/reschedule", data={
        "requested_start": moved.isoformat(timespec="minutes"),
        "requested_end": moved.replace(hour=13).isoformat(timespec="minutes"),
    }).status_code == 302
    assert client.post(f"/appointments/{appointment_id}/cancel").status_code == 302
    with app.app_context():
        events = LifecycleEvent.query.filter_by(appointment_id=appointment_id).order_by(LifecycleEvent.id).all()
        assert [(event.from_status, event.to_status) for event in events][-3:] == [
            ("SCHEDULED", "REQUESTED"),
            ("REQUESTED", "SCHEDULED"),
            ("SCHEDULED", "CANCELLED"),
        ]


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json["status"] == "ok"
    assert response.json["database_dialect"] == "sqlite"


def test_database_health_does_not_expose_credentials(client):
    response = client.get("/health/db")
    assert response.status_code == 200
    assert response.json == {"status": "ok", "database": "reachable", "dialect": "sqlite"}


def test_dashboard_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Good shift. Here's the yard." in response.data
    assert b"Dock utilization (occupied / available time)" in response.data
    assert b"status-chart-data" in response.data
    assert b"direction-chart-data" in response.data


def test_dashboard_alias_and_workflow_pages(client):
    assert client.get("/dashboard").status_code == 200
    assert client.get("/appointments/").status_code == 200
    assert client.get("/reports/").status_code == 200
    assert client.get("/checkins/").status_code == 200
    assert client.get("/exceptions/").status_code == 200
    
def test_simulation_report_is_deterministic_and_read_only(app, client):
    with app.app_context():
        from app.models.operations import Appointment
        before = Appointment.query.count()
    first = client.get("/reports/simulation?seed=55")
    second = client.get("/reports/simulation?seed=55")
    assert first.status_code == 200
    assert b"Appointment simulation" in first.data
    assert b"Projected service minutes" in first.data
    assert first.data == second.data
    with app.app_context():
        assert Appointment.query.count() == before


def test_appointment_rejection_reason_and_audit_are_visible(app, client):
    with app.app_context():
        facility = Facility(code="F-REJ", name="Rejection test")
        carrier = Carrier(code="C-REJ", name="Carrier")
        db.session.add_all([facility, carrier]); db.session.flush()
        db.session.add_all([
            Dock(facility_id=facility.id, code="D-REJ", supports_inbound=False),
            LaborShift(facility_id=facility.id, name="Day", start_time=time(0), end_time=time(23, 59), workers=4),
            YardSlot(facility_id=facility.id, code="Y-REJ", capacity=2),
        ])
        vehicle = Vehicle(carrier_id=carrier.id, registration="V-REJ", vehicle_type="TRUCK")
        db.session.add(vehicle); db.session.flush()
        shipment = Shipment(reference="S-REJ", facility_id=facility.id, carrier_id=carrier.id,
                            vehicle_id=vehicle.id, direction="INBOUND", weight_kg=100)
        db.session.add(shipment); db.session.commit()
        facility_id = facility.id

    start = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
    response = client.post("/appointments/new", data={
        "reference": "A-REJ", "shipment_reference": "S-REJ", "facility_id": facility_id,
        "requested_start": start.isoformat(timespec="minutes"),
        "requested_end": (start + timedelta(hours=2)).isoformat(timespec="minutes"),
        "duration_minutes": "60",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"DOCK_INCOMPATIBLE" in response.data
    with app.app_context():
        appointment = Appointment.query.filter_by(reference="A-REJ").one()
        assert appointment.status == "REJECTED"
        assert SchedulingDecision.query.filter_by(appointment_id=appointment.id, reason_code="DOCK_INCOMPATIBLE").count() == 1
        event = LifecycleEvent.query.filter_by(appointment_id=appointment.id).one()
        assert (event.from_status, event.to_status) == ("REQUESTED", "REJECTED")
        appointment_id = appointment.id
    detail = client.get(f"/appointments/{appointment_id}")
    assert b"DOCK_INCOMPATIBLE" in detail.data
    assert b"Lifecycle history" in detail.data
