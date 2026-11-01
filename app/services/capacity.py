from datetime import timedelta

from sqlalchemy import func

from app import db
from app.models.domain import HandlingRequirement, YardSlot, YardSlotReservation
from app.models.masters import LaborAssignment, LaborShift
from app.models.operations import Appointment, YardOccupancy
from app.models.scheduling import DockReservation


def yard_available(facility, start_at=None, end_at=None, exclude_appointment_id=None):
    if start_at is None:
        occupancy = YardOccupancy.query.filter_by(facility_id=facility.id, exited_at=None).all()
        reservation_ids = {
            row[0] for row in db.session.query(YardSlotReservation.appointment_id)
            .join(Appointment, Appointment.id == YardSlotReservation.appointment_id)
            .filter(
                Appointment.facility_id == facility.id,
                YardSlotReservation.status == "ACTIVE",
            )
            .all()
        }
        return len({row.appointment_id for row in occupancy} | reservation_ids) < facility.yard_capacity

    end_at = end_at or start_at + timedelta(microseconds=1)
    reservations = {
        row[0] for row in db.session.query(YardSlotReservation.appointment_id)
        .join(Appointment, Appointment.id == YardSlotReservation.appointment_id)
        .filter(
            Appointment.facility_id == facility.id,
            YardSlotReservation.status == "ACTIVE",
            YardSlotReservation.start_at < end_at,
            YardSlotReservation.end_at > start_at,
        )
        .all()
    }
    occupancy = {
        row[0] for row in db.session.query(YardOccupancy.appointment_id)
        .filter(
            YardOccupancy.facility_id == facility.id,
            YardOccupancy.entered_at < end_at,
            (YardOccupancy.exited_at.is_(None)) | (YardOccupancy.exited_at > start_at),
        )
        .all()
    }
    active_appointments = reservations | occupancy
    if exclude_appointment_id is not None:
        active_appointments.discard(exclude_appointment_id)
    return len(active_appointments) < facility.yard_capacity


def available_yard_slot(facility, slot_type, start_at, end_at, exclude_appointment_id=None):
    slots = YardSlot.query.filter_by(
        facility_id=facility.id,
        slot_type=slot_type,
        active=True,
    ).order_by(YardSlot.code).all()
    for slot in slots:
        query = YardSlotReservation.query.filter(
            YardSlotReservation.yard_slot_id == slot.id,
            YardSlotReservation.status == "ACTIVE",
            YardSlotReservation.start_at < end_at,
            YardSlotReservation.end_at > start_at,
        )
        if exclude_appointment_id is not None:
            query = query.filter(YardSlotReservation.appointment_id != exclude_appointment_id)
        if query.count() < slot.capacity:
            return slot
    return None


def available_dock(dock, start_at, end_at, exclude_appointment_id=None):
    """Dock capacity is one concurrent appointment in the current schema."""
    query = DockReservation.query.filter(
        DockReservation.dock_id == dock.id,
        DockReservation.status == "ACTIVE",
        DockReservation.start_at < end_at,
        DockReservation.end_at > start_at,
    )
    if exclude_appointment_id is not None:
        query = query.filter(DockReservation.appointment_id != exclude_appointment_id)
    return query.first() is None


def available_labor_shift(facility, start_at, end_at, required_workers=1, exclude_appointment_id=None):
    start = start_at.timetz().replace(tzinfo=None)
    end = end_at.timetz().replace(tzinfo=None)
    shifts = LaborShift.query.filter(
        LaborShift.facility_id == facility.id,
        LaborShift.start_time <= start,
        LaborShift.end_time >= end,
        LaborShift.workers >= required_workers,
    ).order_by(LaborShift.start_time, LaborShift.id).all()
    for shift in shifts:
        query = (
            db.session.query(func.coalesce(func.sum(LaborAssignment.workers), 0))
            .join(Appointment, Appointment.id == LaborAssignment.appointment_id)
            .filter(
                LaborAssignment.shift_id == shift.id,
                Appointment.status == "SCHEDULED",
                Appointment.scheduled_start < end_at,
                Appointment.scheduled_end > start_at,
            )
        )
        if exclude_appointment_id is not None:
            query = query.filter(Appointment.id != exclude_appointment_id)
        assigned_workers = query.scalar() or 0
        legacy_query = (
            db.session.query(func.coalesce(func.sum(func.coalesce(HandlingRequirement.required_workers, 1)), 0))
            .select_from(Appointment)
            .outerjoin(HandlingRequirement, HandlingRequirement.shipment_id == Appointment.shipment_id)
            .filter(
                Appointment.facility_id == facility.id,
                Appointment.status == "SCHEDULED",
                Appointment.scheduled_start < end_at,
                Appointment.scheduled_end > start_at,
                ~db.session.query(LaborAssignment.id)
                .filter(LaborAssignment.appointment_id == Appointment.id)
                .exists(),
            )
        )
        if exclude_appointment_id is not None:
            legacy_query = legacy_query.filter(Appointment.id != exclude_appointment_id)
        legacy_workers = legacy_query.scalar() or 0
        if assigned_workers + legacy_workers + required_workers <= shift.workers:
            return shift
    return None


def labor_available(facility, start_at, end_at, required_workers=1, exclude_appointment_id=None):
    return available_labor_shift(
        facility,
        start_at,
        end_at,
        required_workers=required_workers,
        exclude_appointment_id=exclude_appointment_id,
    ) is not None
