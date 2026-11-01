import pytest
from datetime import datetime, timezone, timedelta, time
from app import db
from app.models.masters import Facility, Carrier, Vehicle
from app.models.operations import Appointment, GateVisit, Shipment
from app.models.events import LifecycleEvent, OperationalException
from app.models.domain import AppointmentTimeline, CheckInEvent, YardSlot, YardSlotReservation
from app.models.masters import Dock, LaborShift
from app.models.scheduling import DockReservation
from app.services.exception_detector import detect_no_show
from app.services.scheduler import schedule_appointment
from app.services.lifecycle import transition


def test_invalid_transition_rejected(app):
    with app.app_context():
        facility = Facility(code="F1", name="Test"); db.session.add(facility); db.session.flush()
        carrier = Carrier(code="C1", name="Carrier"); db.session.add(carrier); db.session.flush()
        vehicle = Vehicle(carrier_id=carrier.id, registration="TRK1", vehicle_type="TRUCK"); db.session.add(vehicle); db.session.flush()
        shipment = Shipment(reference="S1", facility_id=facility.id, carrier_id=carrier.id, vehicle_id=vehicle.id, direction="INBOUND", weight_kg=1); db.session.add(shipment); db.session.flush()
        start = datetime.now(timezone.utc)
        a = Appointment(reference="A1", shipment_id=shipment.id, facility_id=facility.id, requested_start=start, requested_end=start + timedelta(hours=1))
        db.session.add(a); db.session.commit()
        with pytest.raises(ValueError): transition(a, "COMPLETED")


def test_valid_transition_records_event(app):
    with app.app_context():
        facility = Facility(code="F1", name="Test"); db.session.add(facility); db.session.flush()
        carrier = Carrier(code="C1", name="Carrier"); db.session.add(carrier); db.session.flush()
        vehicle = Vehicle(carrier_id=carrier.id, registration="TRK1", vehicle_type="TRUCK"); db.session.add(vehicle); db.session.flush()
        shipment = Shipment(reference="S1", facility_id=facility.id, carrier_id=carrier.id, vehicle_id=vehicle.id, direction="INBOUND", weight_kg=1); db.session.add(shipment); db.session.flush()
        start = datetime.now(timezone.utc)
        a = Appointment(reference="A1", shipment_id=shipment.id, facility_id=facility.id, requested_start=start, requested_end=start + timedelta(hours=1), status="REQUESTED")
        db.session.add(a); db.session.commit()
        transition(a, "CANCELLED")
        assert len(a.events) == 1 and a.events[0].to_status == "CANCELLED"


def scheduled_appointment():
    facility = Facility(code="F1", name="Test", yard_capacity=10)
    carrier = Carrier(code="C1", name="Carrier")
    db.session.add_all([facility, carrier]); db.session.flush()
    db.session.add_all([Dock(facility_id=facility.id, code="D1"), LaborShift(facility_id=facility.id, name="day", start_time=time(6), end_time=time(22), workers=5), YardSlot(facility_id=facility.id, code="Y1", capacity=5)])
    vehicle = Vehicle(carrier_id=carrier.id, registration="TRK1", vehicle_type="TRUCK"); db.session.add(vehicle); db.session.flush()
    start = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    shipment = Shipment(reference="S1", facility_id=facility.id, carrier_id=carrier.id, vehicle_id=vehicle.id, direction="INBOUND", weight_kg=1); db.session.add(shipment); db.session.flush()
    appointment = Appointment(reference="A1", shipment_id=shipment.id, facility_id=facility.id, requested_start=start, requested_end=start + timedelta(hours=2))
    db.session.add(appointment); db.session.flush(); schedule_appointment(appointment)
    return appointment


def test_gate_progression_and_checkout(app, client):
    with app.app_context():
        appointment = scheduled_appointment()
        appointment_id = appointment.id
    assert client.post(f"/checkins/{appointment_id}").status_code == 302
    assert b"Assign dock" in client.get("/checkins/").data
    assert b"Gate check-in" in client.get(f"/appointments/{appointment_id}").data
    assert client.post(f"/checkins/{appointment_id}/complete").status_code == 302
    assert b"Start service" in client.get("/checkins/").data
    assert client.post(f"/checkins/{appointment_id}/complete").status_code == 302
    assert b"Complete service" in client.get("/checkins/").data
    assert client.post(f"/checkins/{appointment_id}/complete").status_code == 302
    assert b"Check out" in client.get("/checkins/").data
    assert client.post(f"/checkins/{appointment_id}/checkout").status_code == 302
    detail = client.get(f"/appointments/{appointment_id}")
    for milestone in (b"Gate check-in", b"Dock arrival", b"Service start", b"Service completion", b"Gate checkout", b"Actual work duration"):
        assert milestone in detail.data
    with app.app_context():
        appointment = db.session.get(Appointment, appointment_id)
        assert appointment.status == "DEPARTED"
        assert len(appointment.events) == 6
        assert (appointment.events[0].from_status, appointment.events[0].to_status) == ("REQUESTED", "SCHEDULED")
        visit = GateVisit.query.filter_by(appointment_id=appointment_id).one()
        timeline = AppointmentTimeline.query.filter_by(appointment_id=appointment_id).one()
        assert visit.check_in_at is not None
        assert visit.check_out_at is not None
        assert timeline.dock_arrival_at is not None
        assert timeline.service_start_at is not None
        assert timeline.service_end_at is not None
        assert timeline.departure_at is not None
        assert (timeline.service_end_at - timeline.service_start_at).total_seconds() >= 0


def test_checkout_before_service_completion_is_rejected(app, client):
    with app.app_context():
        appointment = scheduled_appointment()
        appointment_id = appointment.id
    assert client.post(f"/checkins/{appointment_id}").status_code == 302
    response = client.post(f"/checkins/{appointment_id}/checkout", follow_redirects=True)
    assert response.status_code == 200
    assert b"Appointment must be completed before checkout." in response.data
    with app.app_context():
        appointment = db.session.get(Appointment, appointment_id)
        visit = GateVisit.query.filter_by(appointment_id=appointment_id).one()
        assert appointment.status == "CHECKED_IN"
        assert visit.check_out_at is None


def test_no_show_and_exception_resolution(app, client):
    with app.app_context():
        appointment = scheduled_appointment()
        appointment.requested_end = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.session.commit()
        appointment_id = appointment.id
        exception = detect_no_show(appointment)
        assert exception is not None
        exception_id = exception.id
        assert any(event.event_type == "NO_SHOW_DETECTED" for event in appointment.events)
        assert all(item.status == "CANCELLED" for item in DockReservation.query.filter_by(appointment_id=appointment_id).all())
        assert all(item.status == "CANCELLED" for item in YardSlotReservation.query.filter_by(appointment_id=appointment_id).all())
    response = client.post(f"/exceptions/{exception_id}/resolve", data={"notes": "Reviewed"})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(OperationalException, exception_id).status == "RESOLVED"


def test_no_show_detection_route_releases_resources_and_records_history(app, client):
    with app.app_context():
        appointment = scheduled_appointment()
        appointment.requested_end = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.session.commit()
        appointment_id = appointment.id

    response = client.post("/exceptions/detect-no-shows")
    assert response.status_code == 302
    with app.app_context():
        appointment = db.session.get(Appointment, appointment_id)
        assert appointment.status == "NO_SHOW"
        assert LifecycleEvent.query.filter_by(appointment_id=appointment_id, event_type="NO_SHOW_DETECTED").count() == 1
        assert OperationalException.query.filter_by(appointment_id=appointment_id, cause_code="NO_SHOW").count() == 1
        assert DockReservation.query.filter_by(appointment_id=appointment_id, status="ACTIVE").count() == 0
        assert YardSlotReservation.query.filter_by(appointment_id=appointment_id, status="ACTIVE").count() == 0


def test_early_checkin_is_rejected_and_recorded(app, client):
    with app.app_context():
        appointment = scheduled_appointment()
        appointment.scheduled_start = datetime.now(timezone.utc) + timedelta(hours=1)
        db.session.commit()
        appointment_id = appointment.id
    assert client.post(f"/checkins/{appointment_id}").status_code == 302
    with app.app_context():
        appointment = db.session.get(Appointment, appointment_id)
        assert appointment.status == "SCHEDULED"
        attempt = CheckInEvent.query.filter_by(appointment_id=appointment_id).one()
        assert attempt.outcome == "REJECTED"
        assert attempt.reason_code == "EARLY_CHECK_IN"
