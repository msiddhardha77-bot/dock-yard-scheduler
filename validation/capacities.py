from collections import defaultdict
from datetime import timezone

from app.models.domain import (
    HandlingRequirement,
    YardSlot,
    YardSlotReservation,
)
from app.models.events import AnomalyLabel, GroundTruthRecord
from app.models.masters import Dock, Facility, LaborAssignment, LaborShift
from app.models.operations import Appointment, Shipment
from app.models.scheduling import DockReservation
from app.services.compatibility import (
    compatible,
    handles_requirement,
    handling_yard_slot_type,
)


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _over_capacity_appointments(intervals, capacities):
    grouped = defaultdict(list)
    for resource_id, start, end, amount, appointment_id in intervals:
        grouped[resource_id].append(
            (_utc(start), _utc(end), amount, appointment_id)
        )

    violating_ids = set()
    peak_loads = {}
    for resource_id, resource_intervals in grouped.items():
        events = defaultdict(lambda: {"ends": [], "starts": []})
        for start, end, amount, appointment_id in resource_intervals:
            events[start]["starts"].append((appointment_id, amount))
            events[end]["ends"].append((appointment_id, amount))

        active = {}
        current_load = 0
        peak_load = 0
        ordered_times = sorted(events)
        for index, timestamp in enumerate(ordered_times[:-1]):
            for appointment_id, amount in events[timestamp]["ends"]:
                current_load -= active.pop(appointment_id, amount)
            for appointment_id, amount in events[timestamp]["starts"]:
                active[appointment_id] = amount
                current_load += amount

            peak_load = max(peak_load, current_load)
            if (
                ordered_times[index + 1] > timestamp
                and current_load > capacities[resource_id]
            ):
                violating_ids.update(active)
        peak_loads[resource_id] = peak_load
    return violating_ids, peak_loads


def resource_capacity_summary(session):
    """Validate generated resource allocations and documented anomaly evidence."""
    labels = {
        row.appointment_id: row.label
        for row in session.query(AnomalyLabel).all()
    }
    truth = {
        row.entity_id: row.truth
        for row in session.query(GroundTruthRecord).filter_by(
            entity_type="appointment"
        )
    }

    docks = {row.id: row for row in session.query(Dock).all()}
    facilities = {
        row.id: row for row in session.query(Facility).all()
    }
    slots = {row.id: row for row in session.query(YardSlot).all()}
    shifts = {row.id: row for row in session.query(LaborShift).all()}

    dock_rows = (
        session.query(DockReservation, Dock, Appointment, HandlingRequirement)
        .join(Dock, Dock.id == DockReservation.dock_id)
        .join(Appointment, Appointment.id == DockReservation.appointment_id)
        .join(Shipment, Shipment.id == Appointment.shipment_id)
        .outerjoin(
            HandlingRequirement,
            HandlingRequirement.shipment_id == Shipment.id,
        )
        .filter(
            DockReservation.status == "ACTIVE",
            Appointment.status == "SCHEDULED",
        )
        .all()
    )
    dock_intervals = []
    dock_handling_violations = set()
    dock_assignment_violations = set()
    reservation_by_appointment = {}
    for reservation, dock, appointment, requirement in dock_rows:
        reservation_by_appointment[appointment.id] = reservation
        dock_intervals.append(
            (
                dock.id,
                reservation.start_at,
                reservation.end_at,
                1,
                appointment.id,
            )
        )
        if (
            dock.facility_id != appointment.facility_id
            or not compatible(dock, appointment)
        ):
            dock_assignment_violations.add(appointment.id)
        if requirement and not handles_requirement(dock.dock_type, requirement):
            dock_handling_violations.add(appointment.id)
    dock_capacity_violations, dock_peak_loads = _over_capacity_appointments(
        dock_intervals,
        {dock_id: 1 for dock_id in docks},
    )

    dock_anomaly_id = next(
        (
            appointment_id
            for appointment_id, label in labels.items()
            if label == "DOCK_CAPACITY_EXCEEDED"
        ),
        None,
    )
    dock_truth = truth.get(dock_anomaly_id, {}) if dock_anomaly_id else {}
    conflicting_id = dock_truth.get("conflicting_appointment_id")
    expected_dock_pair = (
        {dock_anomaly_id, conflicting_id}
        if dock_anomaly_id is not None and conflicting_id is not None
        else set()
    )
    expected_dock_reservations = [
        reservation_by_appointment.get(appointment_id)
        for appointment_id in expected_dock_pair
    ]
    dock_evidence_valid = (
        len(expected_dock_pair) == 2
        and expected_dock_pair == dock_capacity_violations
        and all(expected_dock_reservations)
        and len({row.dock_id for row in expected_dock_reservations}) == 1
        and dock_truth.get("dock_id")
        == expected_dock_reservations[0].dock_id
        and max(_utc(row.start_at) for row in expected_dock_reservations)
        < min(_utc(row.end_at) for row in expected_dock_reservations)
    )

    yard_rows = (
        session.query(YardSlotReservation, YardSlot, Appointment, HandlingRequirement)
        .join(YardSlot, YardSlot.id == YardSlotReservation.yard_slot_id)
        .join(Appointment, Appointment.id == YardSlotReservation.appointment_id)
        .join(Shipment, Shipment.id == Appointment.shipment_id)
        .outerjoin(
            HandlingRequirement,
            HandlingRequirement.shipment_id == Shipment.id,
        )
        .filter(
            YardSlotReservation.status == "ACTIVE",
            Appointment.status == "SCHEDULED",
        )
        .all()
    )
    slot_intervals = []
    facility_yard_intervals = []
    yard_assignment_violations = set()
    for reservation, slot, appointment, requirement in yard_rows:
        slot_intervals.append(
            (
                slot.id,
                reservation.start_at,
                reservation.end_at,
                1,
                appointment.id,
            )
        )
        facility_yard_intervals.append(
            (
                appointment.facility_id,
                reservation.start_at,
                reservation.end_at,
                1,
                appointment.id,
            )
        )
        if (
            slot.facility_id != appointment.facility_id
            or slot.slot_type != handling_yard_slot_type(requirement)
        ):
            yard_assignment_violations.add(appointment.id)
    slot_capacity_violations, slot_peak_loads = _over_capacity_appointments(
        slot_intervals,
        {slot_id: slot.capacity for slot_id, slot in slots.items()},
    )
    facility_capacity_violations, facility_peak_loads = (
        _over_capacity_appointments(
            facility_yard_intervals,
            {
                facility_id: facility.yard_capacity
                for facility_id, facility in facilities.items()
            },
        )
    )

    labor_rows = (
        session.query(LaborAssignment, LaborShift, Appointment, HandlingRequirement)
        .join(LaborShift, LaborShift.id == LaborAssignment.shift_id)
        .join(Appointment, Appointment.id == LaborAssignment.appointment_id)
        .join(Shipment, Shipment.id == Appointment.shipment_id)
        .outerjoin(
            HandlingRequirement,
            HandlingRequirement.shipment_id == Shipment.id,
        )
        .filter(Appointment.status == "SCHEDULED")
        .all()
    )
    labor_intervals = []
    labor_assignment_violations = set()
    assignment_by_appointment = {}
    for assignment, shift, appointment, requirement in labor_rows:
        assignment_by_appointment[appointment.id] = (assignment, shift)
        labor_intervals.append(
            (
                shift.id,
                appointment.scheduled_start,
                appointment.scheduled_end,
                assignment.workers,
                appointment.id,
            )
        )
        required_workers = requirement.required_workers if requirement else 1
        if (
            shift.facility_id != appointment.facility_id
            or assignment.workers != required_workers
            or appointment.scheduled_start.time().replace(tzinfo=None)
            < shift.start_time
            or appointment.scheduled_end.time().replace(tzinfo=None)
            > shift.end_time
        ):
            labor_assignment_violations.add(appointment.id)
    labor_capacity_violations, labor_peak_loads = _over_capacity_appointments(
        labor_intervals,
        {shift_id: shift.workers for shift_id, shift in shifts.items()},
    )
    labor_anomaly_id = next(
        (
            appointment_id
            for appointment_id, label in labels.items()
            if label == "LABOR_UNAVAILABLE"
        ),
        None,
    )
    labor_truth = truth.get(labor_anomaly_id, {}) if labor_anomaly_id else {}
    labor_pair = (
        assignment_by_appointment.get(labor_anomaly_id)
        if labor_anomaly_id is not None
        else None
    )
    labor_assignment, labor_shift = labor_pair if labor_pair else (None, None)
    assignments_on_anomaly_shift = (
        session.query(LaborAssignment)
        .filter_by(shift_id=labor_shift.id)
        .count()
        if labor_shift
        else 0
    )
    labor_evidence_valid = bool(
        labor_assignment
        and labor_shift
        and labor_assignment.shift_id == labor_truth.get("shift_id")
        and labor_shift.workers == labor_truth.get("available_workers")
        and labor_assignment.workers == labor_truth.get("assigned_workers")
        and labor_assignment.workers > labor_shift.workers
        and assignments_on_anomaly_shift == 1
        and labor_truth.get("recurring_shift_id") in shifts
        and shifts[labor_truth["recurring_shift_id"]].workers
        > labor_shift.workers
        and labor_capacity_violations == {labor_anomaly_id}
    )

    incompatible_id = next(
        (
            appointment_id
            for appointment_id, label in labels.items()
            if label == "INCOMPATIBLE_LOAD_ASSIGNMENT"
        ),
        None,
    )
    incompatible_truth = truth.get(incompatible_id, {}) if incompatible_id else {}
    incompatible_evidence_valid = bool(
        incompatible_id is not None
        and dock_handling_violations == {incompatible_id}
        and incompatible_id in reservation_by_appointment
        and incompatible_truth.get("dock_id")
        == reservation_by_appointment[incompatible_id].dock_id
    )

    return {
        "dock": {
            "over_capacity_appointment_ids": sorted(dock_capacity_violations),
            "peak_load_by_dock": dock_peak_loads,
            "intentional_conflict_appointment_ids": sorted(expected_dock_pair),
            "intentional_evidence_valid": bool(dock_evidence_valid),
            "unintended_over_capacity_appointment_ids": sorted(
                dock_capacity_violations - expected_dock_pair
            ),
            "assignment_violations": sorted(dock_assignment_violations),
            "handling_violations": sorted(dock_handling_violations),
        },
        "yard": {
            "slot_over_capacity_appointment_ids": sorted(
                slot_capacity_violations
            ),
            "facility_over_capacity_appointment_ids": sorted(
                facility_capacity_violations
            ),
            "peak_load_by_slot": slot_peak_loads,
            "peak_load_by_facility": facility_peak_loads,
            "assignment_violations": sorted(yard_assignment_violations),
        },
        "labor": {
            "over_capacity_appointment_ids": sorted(labor_capacity_violations),
            "peak_load_by_shift": labor_peak_loads,
            "intentional_anomaly_appointment_id": labor_anomaly_id,
            "intentional_evidence_valid": bool(labor_evidence_valid),
            "unintended_over_capacity_appointment_ids": sorted(
                labor_capacity_violations - {labor_anomaly_id}
                if labor_anomaly_id is not None
                else labor_capacity_violations
            ),
            "assignment_violations": sorted(labor_assignment_violations),
            "assignments_on_anomaly_shift": assignments_on_anomaly_shift,
        },
        "incompatible_handling": {
            "appointment_ids": sorted(dock_handling_violations),
            "intentional_anomaly_appointment_id": incompatible_id,
            "intentional_evidence_valid": bool(incompatible_evidence_valid),
            "dock_assignment_violations": sorted(dock_assignment_violations),
        },
    }
