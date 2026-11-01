from datetime import datetime, timezone, time
from app import db
from app.models.masters import Facility, Dock, Carrier, Vehicle, LaborShift
from app.models.operations import Shipment, Appointment
from app.models.domain import HandlingRequirement, YardSlot, YardSlotReservation
from app.models.masters import LaborAssignment
from app.models.events import LifecycleEvent
from app.models.scheduling import DockReservation, SchedulingDecision
from app.services.scheduler import cancel_appointment, reschedule_appointment, schedule_appointment


def make_appointment(reference="A1", shipment_reference="S1", registration="TRK1"):
    suffix = reference.replace("-", "")
    facility = Facility(code=f"F{suffix}", name="Test", yard_capacity=10)
    carrier = Carrier(code=f"C{suffix}", name="Carrier")
    db.session.add_all([facility, carrier]); db.session.flush()
    db.session.add_all([
        Dock(facility_id=facility.id, code="D1"),
        LaborShift(facility_id=facility.id, name="day", start_time=time(6), end_time=time(22), workers=5),
        YardSlot(facility_id=facility.id, code="Y1", capacity=1),
    ])
    vehicle = Vehicle(carrier_id=carrier.id, registration=registration, vehicle_type="TRUCK"); db.session.add(vehicle); db.session.flush()
    shipment = Shipment(reference=shipment_reference, facility_id=facility.id, carrier_id=carrier.id, vehicle_id=vehicle.id, direction="INBOUND", weight_kg=1000)
    db.session.add(shipment); db.session.flush()
    appointment = Appointment(reference=reference, shipment_id=shipment.id, facility_id=facility.id,
                              requested_start=datetime(2026, 10, 30, 10, tzinfo=timezone.utc), requested_end=datetime(2026, 10, 30, 12, tzinfo=timezone.utc))
    db.session.add(appointment); db.session.commit()
    return appointment


def test_scheduling_allocates_compatible_dock(app):
    with app.app_context():
        appointment = make_appointment()
        reservation = schedule_appointment(appointment)
        assert reservation is not None
        assert appointment.status == "SCHEDULED"


def test_scheduling_already_scheduled_appointment_preserves_reservation(app):
    with app.app_context():
        appointment = make_appointment()
        reservation = schedule_appointment(appointment)
        assert reservation is not None

        assert schedule_appointment(appointment) is None

        assert appointment.status == "SCHEDULED"
        assert DockReservation.query.filter_by(
            appointment_id=appointment.id,
            status="ACTIVE",
        ).count() == 1
        decisions = SchedulingDecision.query.filter_by(
            appointment_id=appointment.id
        ).order_by(SchedulingDecision.id).all()
        assert [decision.decision for decision in decisions] == [
            "ACCEPTED",
            "REJECTED",
        ]
        assert decisions[-1].reason_code == "INVALID_STATUS"
        assert [
            (event.from_status, event.to_status)
            for event in LifecycleEvent.query.filter_by(
                appointment_id=appointment.id
            ).order_by(LifecycleEvent.id)
        ] == [("REQUESTED", "SCHEDULED")]


def test_overlapping_booking_is_rejected(app):
    with app.app_context():
        first = make_appointment(); assert schedule_appointment(first)
        second_shipment = Shipment(reference="S2", facility_id=first.facility_id, carrier_id=first.shipment.carrier_id,
                                    vehicle_id=first.shipment.vehicle_id, direction="INBOUND", weight_kg=1000)
        db.session.add(second_shipment); db.session.flush()
        second = Appointment(reference="A2", shipment_id=second_shipment.id, facility_id=first.facility_id,
                             requested_start=first.requested_start, requested_end=first.requested_end)
        db.session.add(second); db.session.commit()
        assert schedule_appointment(second) is None
        assert second.status == "REJECTED"


def test_outside_operating_hours_is_rejected(app):
    with app.app_context():
        appointment = make_appointment()
        appointment.requested_start = appointment.requested_start.replace(hour=23)
        appointment.requested_end = appointment.requested_start.replace(hour=23, minute=30)
        db.session.commit()
        assert schedule_appointment(appointment) is None
        assert appointment.status == "REJECTED"


def test_incompatible_dock_labor_and_yard_rejections(app):
    with app.app_context():
        appointment = make_appointment("A2", "S2", "TRK2")
        appointment.facility.docks[0].vehicle_types = "VAN"
        db.session.commit()
        assert schedule_appointment(appointment) is None
        assert appointment.status == "REJECTED"

        labor_case = make_appointment("A3", "S3", "TRK3")
        from app.models.masters import LaborShift
        LaborShift.query.filter_by(facility_id=labor_case.facility_id).update({"workers": 0})
        db.session.commit()
        assert schedule_appointment(labor_case) is None
        assert labor_case.status == "REJECTED"

        yard_case = make_appointment("A4", "S4", "TRK4")
        yard_case.facility.yard_capacity = 0
        db.session.commit()
        assert schedule_appointment(yard_case) is None
        assert yard_case.status == "REJECTED"


def test_cancel_and_reschedule_release_and_reallocate(app):
    with app.app_context():
        appointment = make_appointment()
        assert schedule_appointment(appointment)
        moved_start = appointment.requested_start.replace(hour=11)
        assert reschedule_appointment(appointment, moved_start, moved_start.replace(hour=13))
        assert appointment.scheduled_start == moved_start
        cancel_appointment(appointment)
        assert appointment.status == "CANCELLED"
        assert appointment.shipment is not None
        replacement = make_appointment("A2", "S2", "TRK2")
        assert schedule_appointment(replacement)
        assert replacement.status == "SCHEDULED"


def test_handling_requirement_requires_specialized_dock(app):
    with app.app_context():
        appointment = make_appointment("A5", "S5", "TRK5")
        db.session.add(HandlingRequirement(shipment_id=appointment.shipment_id, refrigerated=True))
        db.session.commit()
        assert schedule_appointment(appointment) is None
        assert appointment.status == "REJECTED"
        appointment.facility.docks[0].dock_type = "REFRIGERATED"
        db.session.add(YardSlot(facility_id=appointment.facility_id, code="YARD-COLD", capacity=1, slot_type="REFRIGERATED"))
        db.session.commit()
        assert schedule_appointment(appointment) is not None
        history = LifecycleEvent.query.filter_by(appointment_id=appointment.id).order_by(LifecycleEvent.id).all()
        assert [(event.from_status, event.to_status) for event in history] == [
            ("REQUESTED", "REJECTED"),
            ("REJECTED", "REQUESTED"),
            ("REQUESTED", "SCHEDULED"),
        ]


def test_combined_handling_requires_dual_compatible_dock_and_yard_slot(app):
    with app.app_context():
        appointment = make_appointment("DUAL1", "DUALS1", "DUALTRUCK1")
        db.session.add(HandlingRequirement(
            shipment_id=appointment.shipment_id,
            refrigerated=True,
            hazardous=True,
        ))
        appointment.facility.docks[0].dock_type = "REFRIGERATED_HAZARDOUS"
        db.session.add(YardSlot(
            facility_id=appointment.facility_id,
            code="DUAL-YARD",
            capacity=1,
            slot_type="REFRIGERATED_HAZARDOUS",
        ))
        db.session.commit()
        assert schedule_appointment(appointment)


def test_handling_requirement_without_dual_capable_dock_is_rejected(app):
    with app.app_context():
        appointment = make_appointment("DUALBAD1", "DUALBADS1", "DUALBADTRUCK1")
        db.session.add(HandlingRequirement(
            shipment_id=appointment.shipment_id,
            refrigerated=True,
            hazardous=True,
        ))
        db.session.add(YardSlot(
            facility_id=appointment.facility_id,
            code="DUALBAD-YARD",
            capacity=1,
            slot_type="REFRIGERATED_HAZARDOUS",
        ))
        db.session.commit()
        assert schedule_appointment(appointment) is None
        decision = SchedulingDecision.query.filter_by(
            appointment_id=appointment.id
        ).order_by(SchedulingDecision.id.desc()).first()
        assert decision.reason_code == "HANDLING_REQUIREMENTS_INCOMPATIBLE"


def test_scheduling_rejects_full_overlapping_yard_slot(app):
    with app.app_context():
        first = make_appointment("YARD1", "YARDS1")
        first.facility.yard_capacity = 10
        db.session.add(Dock(facility_id=first.facility_id, code="D2"))
        assert schedule_appointment(first) is not None

        second = make_appointment("YARD2", "YARDS2", "TRK-YARD2")
        second.facility_id = first.facility_id
        second.shipment.facility_id = first.facility_id
        db.session.commit()

        assert schedule_appointment(second) is None
        assert second.status == "REJECTED"
        reservation = YardSlotReservation.query.filter_by(appointment_id=first.id).one()
        assert reservation.yard_slot.capacity == 1


def test_yard_slot_capacity_allows_capacity_and_rejects_next_overlap(app):
    with app.app_context():
        first = make_appointment("SLOT1", "SLOTS1")
        first.facility.yard_capacity = 10
        YardSlot.query.filter_by(facility_id=first.facility_id).one().capacity = 2
        db.session.add_all([
            Dock(facility_id=first.facility_id, code="D2"),
            Dock(facility_id=first.facility_id, code="D3"),
        ])
        assert schedule_appointment(first)

        def another(reference):
            appointment = make_appointment(reference, f"{reference}-SHIP", f"{reference}-TRUCK")
            appointment.facility_id = first.facility_id
            appointment.shipment.facility_id = first.facility_id
            db.session.commit()
            return appointment

        second = another("SLOT2")
        third = another("SLOT3")
        assert schedule_appointment(second)
        assert schedule_appointment(third) is None
        reason = SchedulingDecision.query.filter_by(
            appointment_id=third.id
        ).order_by(SchedulingDecision.id.desc()).first().reason_code
        assert reason == "YARD_SLOT_UNAVAILABLE"


def test_facility_yard_capacity_rejects_overlapping_appointment(app):
    with app.app_context():
        first = make_appointment("FACCAP1", "FACCAPS1")
        first.facility.yard_capacity = 1
        db.session.add(Dock(facility_id=first.facility_id, code="D2"))
        YardSlot.query.filter_by(facility_id=first.facility_id).one().capacity = 5
        assert schedule_appointment(first)

        second = make_appointment("FACCAP2", "FACCAPS2", "FACCAPTRUCK2")
        second.facility_id = first.facility_id
        second.shipment.facility_id = first.facility_id
        db.session.commit()
        assert schedule_appointment(second) is None
        reason = SchedulingDecision.query.filter_by(
            appointment_id=second.id
        ).order_by(SchedulingDecision.id.desc()).first().reason_code
        assert reason == "YARD_CAPACITY_EXCEEDED"


def test_scheduling_consumes_labor_workers_for_overlapping_assignments(app):
    with app.app_context():
        first = make_appointment("LABOR1", "LABORS1")
        shift = first.facility and LaborShift.query.filter_by(facility_id=first.facility_id).one()
        shift.workers = 2
        YardSlot.query.filter_by(facility_id=first.facility_id).one().capacity = 10
        db.session.add(Dock(facility_id=first.facility_id, code="D2"))
        db.session.add(HandlingRequirement(shipment_id=first.shipment_id, required_workers=1))
        assert schedule_appointment(first) is not None

        second = make_appointment("LABOR2", "LABORS2", "TRK-LABOR2")
        second.facility_id = first.facility_id
        second.shipment.facility_id = first.facility_id
        second_shift = LaborShift.query.filter_by(facility_id=second.facility_id).one()
        second_shift.workers = 2
        db.session.add(HandlingRequirement(shipment_id=second.shipment_id, required_workers=2))
        db.session.commit()

        assert schedule_appointment(second) is None
        assert second.status == "REJECTED"
        assignment = LaborAssignment.query.filter_by(appointment_id=first.id).one()
        assert assignment.workers == 1


def test_legacy_scheduled_appointment_without_assignment_consumes_labor(app):
    with app.app_context():
        first = make_appointment("LEGACY1", "LEGACYS1")
        shift = LaborShift.query.filter_by(facility_id=first.facility_id).one()
        shift.workers = 1
        YardSlot.query.filter_by(facility_id=first.facility_id).one().capacity = 10
        db.session.add(Dock(facility_id=first.facility_id, code="D2"))
        assert schedule_appointment(first) is not None
        assignment = LaborAssignment.query.filter_by(appointment_id=first.id).one()
        db.session.delete(assignment)
        db.session.commit()

        second = make_appointment("LEGACY2", "LEGACYS2", "TRK-LEGACY2")
        second.facility_id = first.facility_id
        second.shipment.facility_id = first.facility_id
        db.session.commit()

        assert schedule_appointment(second) is None
        decision = SchedulingDecision.query.filter_by(appointment_id=second.id).order_by(SchedulingDecision.id.desc()).first()
        assert decision.reason_code == "LABOR_UNAVAILABLE"


def test_vehicle_capacity_and_outbound_dock_support_are_enforced(app):
    with app.app_context():
        appointment = make_appointment("VEH1", "VEHS1")
        appointment.shipment.weight_kg = appointment.shipment.vehicle.capacity_kg + 1
        db.session.commit()
        assert schedule_appointment(appointment) is None
        assert SchedulingDecision.query.filter_by(appointment_id=appointment.id).order_by(SchedulingDecision.id.desc()).first().reason_code == "VEHICLE_CAPACITY_EXCEEDED"

        outbound = make_appointment("OUT1", "OUTS1", "TRK-OUT1")
        outbound.shipment.direction = "OUTBOUND"
        outbound.facility.docks[0].supports_outbound = False
        db.session.commit()
        assert schedule_appointment(outbound) is None
        assert SchedulingDecision.query.filter_by(appointment_id=outbound.id).order_by(SchedulingDecision.id.desc()).first().reason_code == "DOCK_INCOMPATIBLE"


def test_scheduling_rejects_inconsistent_shipment_relationships_and_values(app):
    with app.app_context():
        facility_mismatch = make_appointment("FACILITY1", "FACILITYS1")
        other_facility = Facility(code="OTHER", name="Other")
        db.session.add(other_facility)
        db.session.flush()
        facility_mismatch.shipment.facility_id = other_facility.id
        db.session.commit()
        assert schedule_appointment(facility_mismatch) is None
        assert SchedulingDecision.query.filter_by(
            appointment_id=facility_mismatch.id
        ).order_by(SchedulingDecision.id.desc()).first().reason_code == "SHIPMENT_FACILITY_MISMATCH"

        carrier_mismatch = make_appointment("CARRIER1", "CARRIERS1", "TRK-CARRIER1")
        other_carrier = Carrier(code="OTHER-CARRIER", name="Other carrier")
        db.session.add(other_carrier)
        db.session.flush()
        carrier_mismatch.shipment.carrier_id = other_carrier.id
        db.session.commit()
        assert schedule_appointment(carrier_mismatch) is None
        assert SchedulingDecision.query.filter_by(
            appointment_id=carrier_mismatch.id
        ).order_by(SchedulingDecision.id.desc()).first().reason_code == "VEHICLE_CARRIER_MISMATCH"


def test_outbound_booking_uses_outbound_capable_dock(app):
    with app.app_context():
        appointment = make_appointment("OUTBOUND1", "OUTBOUNDS1", "TRK-OUTBOUND1")
        appointment.shipment.direction = "OUTBOUND"
        appointment.facility.docks[0].supports_inbound = False
        appointment.facility.docks[0].supports_outbound = True
        db.session.commit()

        reservation = schedule_appointment(appointment)

        assert reservation is not None
        assert appointment.status == "SCHEDULED"
        assert reservation.dock.supports_outbound is True


def test_schedule_cancel_and_reschedule_write_lifecycle_history(app):
    with app.app_context():
        appointment = make_appointment("AUDIT1", "AUDITS1")
        assert schedule_appointment(appointment) is not None
        initial = LifecycleEvent.query.filter_by(appointment_id=appointment.id).all()
        assert [(event.from_status, event.to_status) for event in initial] == [("REQUESTED", "SCHEDULED")]

        moved = appointment.requested_start.replace(hour=11)
        assert reschedule_appointment(appointment, moved, moved.replace(hour=13)) is not None
        cancel_appointment(appointment)

        history = LifecycleEvent.query.filter_by(appointment_id=appointment.id).order_by(LifecycleEvent.id).all()
        assert [(event.from_status, event.to_status) for event in history] == [
            ("REQUESTED", "SCHEDULED"),
            ("SCHEDULED", "REQUESTED"),
            ("REQUESTED", "SCHEDULED"),
            ("SCHEDULED", "CANCELLED"),
        ]
