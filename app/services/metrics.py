from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func

from app.models.events import OperationalException
from app.models.operations import Appointment
from app.models.scheduling import DockReservation, SchedulingDecision
from app.models.domain import (
    AppointmentTimeline,
    HandlingRequirement,
    YardSlotReservation,
)
from app.models.masters import Dock, LaborAssignment, LaborShift


# A scheduled appointment remains part of the accepted/scheduled KPI through
# its operational lifecycle.  The status chart still exposes every raw status.
SCHEDULED_LIFECYCLE_STATUSES = (
    "SCHEDULED",
    "CHECKED_IN",
    "AT_DOCK",
    "IN_SERVICE",
    "COMPLETED",
    "DEPARTED",
)


def appointment_status_counts():
    rows = (
        Appointment.query
        .with_entities(Appointment.status, func.count(Appointment.id))
        .group_by(Appointment.status)
        .order_by(Appointment.status)
        .all()
    )
    return {status: count for status, count in rows}


def dashboard_metrics():
    total = Appointment.query.count()
    scheduled = Appointment.query.filter(
        Appointment.status.in_(SCHEDULED_LIFECYCLE_STATUSES)
    ).count()
    rejected = Appointment.query.filter_by(status="REJECTED").count()
    completed = Appointment.query.filter(
        Appointment.status.in_(["COMPLETED", "DEPARTED"])
    ).count()
    delayed = OperationalException.query.filter_by(
        cause_code="LATE_ARRIVAL"
    ).count()

    active_reservations = DockReservation.query.filter_by(
        status="ACTIVE"
    ).count()

    utilization = dock_utilization_metrics()
    throughput = throughput_metrics()

    return {
        "total": total,
        "scheduled": scheduled,
        "rejected": rejected,
        "completed": completed,
        "cancelled": Appointment.query.filter_by(status="CANCELLED").count(),
        "no_show": Appointment.query.filter_by(status="NO_SHOW").count(),
        "delayed": delayed,
        "open_exceptions": OperationalException.query.filter_by(status="OPEN").count(),
        "resolved_exceptions": OperationalException.query.filter_by(status="RESOLVED").count(),
        "active_reservations": active_reservations,
        "inbound_appointments": Appointment.query.join(
            Appointment.shipment
        ).filter_by(direction="INBOUND").count(),
        "outbound_appointments": Appointment.query.join(
            Appointment.shipment
        ).filter_by(direction="OUTBOUND").count(),
        "dock_utilization": utilization["dock_utilization"] or 0,
        "throughput_count": throughput["throughput_count"],
    }


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _merge_minutes(intervals):
    """Return the union length of UTC datetime intervals in minutes."""
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    start, end = ordered[0]
    minutes = 0.0
    for next_start, next_end in ordered[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            minutes += (end - start).total_seconds() / 60
            start, end = next_start, next_end
    return minutes + (end - start).total_seconds() / 60


def dock_utilization_metrics(start_at=None, end_at=None):
    """Calculate dock utilization from actual timeline intervals.

    The numerator is the per-dock union of actual dock-arrival-to-service-end
    intervals for active reservations.  With no explicit window, the window is
    the UTC calendar period containing those observed intervals.  The
    denominator is active docks multiplied by each facility's operating
    minutes in that window.
    """
    rows = (
        DockReservation.query
        .join(Appointment, Appointment.id == DockReservation.appointment_id)
        .join(AppointmentTimeline, AppointmentTimeline.appointment_id == Appointment.id)
        .with_entities(
            DockReservation.dock_id,
            AppointmentTimeline.dock_arrival_at,
            AppointmentTimeline.service_end_at,
        )
        .filter(
            DockReservation.status == "ACTIVE",
            Appointment.status.in_(SCHEDULED_LIFECYCLE_STATUSES),
            AppointmentTimeline.dock_arrival_at.isnot(None),
            AppointmentTimeline.service_end_at.isnot(None),
        )
        .all()
    )
    observed = [
        (_utc(row.dock_arrival_at), _utc(row.service_end_at))
        for row in rows
    ]
    if not observed:
        return {
            "occupied_dock_minutes": 0.0,
            "available_dock_minutes": 0.0,
            "dock_utilization": None,
            "period_start": None,
            "period_end": None,
        }

    if start_at is None:
        start_at = min(start for start, _ in observed).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        start_at = _utc(start_at)
    if end_at is None:
        last = max(end for _, end in observed)
        end_at = (last.replace(hour=0, minute=0, second=0, microsecond=0)
                  + timedelta(days=1))
    else:
        end_at = _utc(end_at)
    if end_at <= start_at:
        return {
            "occupied_dock_minutes": 0.0,
            "available_dock_minutes": 0.0,
            "dock_utilization": None,
            "period_start": start_at,
            "period_end": end_at,
        }

    intervals_by_dock = defaultdict(list)
    for row in rows:
        interval_start = max(_utc(row.dock_arrival_at), start_at)
        interval_end = min(_utc(row.service_end_at), end_at)
        if interval_end > interval_start:
            intervals_by_dock[row.dock_id].append((interval_start, interval_end))
    occupied = sum(_merge_minutes(intervals) for intervals in intervals_by_dock.values())

    # Capacity is based on every active dock, not only docks that happened to
    # receive a reservation in the numerator.
    docks = {dock.id: dock for dock in Dock.query.filter_by(active=True).all()}
    docks_by_facility = defaultdict(list)
    for dock in docks.values():
        docks_by_facility[dock.facility_id].append(dock)
    available = 0.0
    for facility_id, facility_docks in docks_by_facility.items():
        facility = facility_docks[0].facility
        facility_timezone = ZoneInfo(facility.timezone or "UTC")
        local_start = start_at.astimezone(facility_timezone).date()
        local_end = (end_at - timedelta(microseconds=1)).astimezone(
            facility_timezone
        ).date()
        day = local_start
        while day <= local_end:
            if facility.operating_end > facility.operating_start:
                open_at = datetime.combine(
                    day, facility.operating_start, tzinfo=facility_timezone
                ).astimezone(timezone.utc)
                close_at = datetime.combine(
                    day, facility.operating_end, tzinfo=facility_timezone
                ).astimezone(timezone.utc)
                available += len(facility_docks) * max(
                    0.0,
                    (min(close_at, end_at) - max(open_at, start_at)).total_seconds()
                    / 60,
                )
            day += timedelta(days=1)

    return {
        "occupied_dock_minutes": round(occupied, 2),
        "available_dock_minutes": round(available, 2),
        "dock_utilization": round(occupied / available * 100, 2) if available else None,
        "period_start": start_at,
        "period_end": end_at,
    }


def throughput_metrics(start_at=None, end_at=None, facility_id=None):
    """Count completed/departed appointments by actual terminal timestamps.

    `COMPLETED` rows use `service_end_at`; `DEPARTED` rows use
    `departure_at`.  The optional window is half-open: ``[start_at, end_at)``.
    Daily buckets are UTC dates and facility buckets use the appointment's
    facility ID. Rows without the required terminal timestamp are excluded.
    """
    rows = (
        Appointment.query
        .join(AppointmentTimeline, AppointmentTimeline.appointment_id == Appointment.id)
        .with_entities(
            Appointment.status,
            Appointment.facility_id,
            AppointmentTimeline.service_end_at,
            AppointmentTimeline.departure_at,
        )
        .filter(Appointment.status.in_(["COMPLETED", "DEPARTED"]))
        .all()
    )

    start = _utc(start_at) if start_at is not None else None
    end = _utc(end_at) if end_at is not None else None
    terminal_rows = []
    for row in rows:
        terminal = row.departure_at if row.status == "DEPARTED" else row.service_end_at
        if terminal is None:
            continue
        terminal = _utc(terminal)
        if start is not None and terminal < start:
            continue
        if end is not None and terminal >= end:
            continue
        terminal_rows.append((row.status, row.facility_id, terminal))

    if start is None and terminal_rows:
        start = min(row[2] for row in terminal_rows).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if end is None and terminal_rows:
        end = max(row[2] for row in terminal_rows).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)

    daily = defaultdict(int)
    facilities = defaultdict(int)
    for _, row_facility_id, terminal in terminal_rows:
        daily[terminal.date().isoformat()] += 1
        facilities[str(row_facility_id)] += 1

    return {
        "throughput_count": len(terminal_rows),
        "completed_count": sum(row[0] == "COMPLETED" for row in terminal_rows),
        "departed_count": sum(row[0] == "DEPARTED" for row in terminal_rows),
        "daily": dict(sorted(daily.items())),
        "by_facility": dict(sorted(facilities.items())),
        "period_start": start,
        "period_end": end,
    }


def evaluation_metrics():
    total = Appointment.query.count()
    accepted = SchedulingDecision.query.filter_by(decision="ACCEPTED").count()
    rejected = SchedulingDecision.query.filter_by(decision="REJECTED").count()
    decisions = accepted + rejected

    completed = Appointment.query.filter(
        Appointment.status.in_(["COMPLETED", "DEPARTED"])
    ).count()

    return {
        "appointment_count": total,
        "accepted_decisions": accepted,
        "rejected_decisions": rejected,
        "decision_count": decisions,
        "acceptance_rate": round(accepted / decisions * 100, 2) if decisions else 0,
        "rejection_rate": round(rejected / decisions * 100, 2) if decisions else 0,
        "completed_count": completed,
        "cancelled_count": Appointment.query.filter_by(status="CANCELLED").count(),
        "no_show_count": Appointment.query.filter_by(status="NO_SHOW").count(),
        "open_exception_count": OperationalException.query.filter_by(status="OPEN").count(),
        "exception_count": OperationalException.query.count(),
        "active_reservation_count": DockReservation.query.filter_by(status="ACTIVE").count(),
    }


def timeline_metrics():
    timelines = (
        AppointmentTimeline.query
        .join(AppointmentTimeline.appointment)
        .filter(Appointment.status.in_(SCHEDULED_LIFECYCLE_STATUSES))
        .all()
    )

    waits = [
        (row.service_start_at - row.actual_arrival_at).total_seconds() / 60
        for row in timelines
        if row.service_start_at and row.actual_arrival_at
    ]

    dock_minutes = sum(
        (row.service_end_at - row.dock_arrival_at).total_seconds() / 60
        for row in timelines
        if row.service_end_at and row.dock_arrival_at
    )

    yard_minutes = sum(
        (row.departure_at - row.yard_entry_at).total_seconds() / 60
        for row in timelines
        if row.departure_at and row.yard_entry_at
    )

    return {
        "wait_time_minutes": round(sum(waits) / len(waits), 2) if waits else None,
        "dock_occupied_minutes": round(dock_minutes, 2),
        "yard_occupied_minutes": round(yard_minutes, 2),
        "timeline_sample_size": len(timelines),
        "yard_slot_reservation_count": YardSlotReservation.query.count(),
    }


def _naive_datetime(value):
    """Normalize database datetimes for safe comparison."""
    if value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def labor_utilization_metrics():
    """
    Calculate planned labor utilization for SCHEDULED appointments.

    Assumptions:
    - Labor shifts repeat every day.
    - The reporting period is calculated separately for each facility.
    - Appointments without assignments use HandlingRequirement.required_workers.
    - Legacy appointments are matched to the first shift that fully contains them.
    """

    appointments = Appointment.query.filter(
        Appointment.status == "SCHEDULED",
        Appointment.scheduled_start.isnot(None),
        Appointment.scheduled_end.isnot(None),
    ).all()

    if not appointments:
        return {
            "available_worker_hours": 0,
            "planned_worker_hours": 0,
            "labor_utilization_percent": None,
            "labor_shift_count": 0,
            "scheduled_appointment_count": 0,
            "unassigned_appointment_count": 0,
        }

    appointment_ids = [a.id for a in appointments]
    shipment_ids = list({a.shipment_id for a in appointments})
    facility_ids = list({a.facility_id for a in appointments})

    assignments = LaborAssignment.query.filter(
        LaborAssignment.appointment_id.in_(appointment_ids)
    ).all()

    assignment_by_appointment = {}
    for assignment in assignments:
        assignment_by_appointment.setdefault(
            assignment.appointment_id, assignment
        )

    requirements = HandlingRequirement.query.filter(
        HandlingRequirement.shipment_id.in_(shipment_ids)
    ).all()
    requirement_by_shipment = {
        requirement.shipment_id: requirement
        for requirement in requirements
    }

    shifts = LaborShift.query.filter(
        LaborShift.facility_id.in_(facility_ids)
    ).order_by(
        LaborShift.start_time,
        LaborShift.id,
    ).all()

    shifts_by_facility = defaultdict(list)
    shifts_by_id = {}

    for shift in shifts:
        shifts_by_facility[shift.facility_id].append(shift)
        shifts_by_id[shift.id] = shift

    appointments_by_facility = defaultdict(list)

    for appointment in appointments:
        appointments_by_facility[appointment.facility_id].append(appointment)

    available_worker_minutes = 0
    planned_worker_minutes = 0
    unassigned_count = 0
    used_shift_ids = set()

    for facility_id, facility_appointments in appointments_by_facility.items():

        dates = [
            _naive_datetime(a.scheduled_start).date()
            for a in facility_appointments
        ]

        first_date = min(dates)
        last_date = max(dates)
        number_of_days = (last_date - first_date).days + 1

        facility_shifts = shifts_by_facility[facility_id]

        # Calculate available worker-minutes for every recurring shift.
        for shift in facility_shifts:
            shift_start = shift.start_time
            shift_end = shift.end_time

            # Overnight shifts are not supported by the current scheduler.
            if shift_end <= shift_start:
                continue

            shift_minutes = (
                datetime.combine(first_date, shift_end)
                - datetime.combine(first_date, shift_start)
            ).total_seconds() / 60

            available_worker_minutes += (
                shift.workers * shift_minutes * number_of_days
            )

        # Calculate planned worker-minutes from scheduled appointments.
        for appointment in facility_appointments:

            appointment_start = _naive_datetime(
                appointment.scheduled_start
            )
            appointment_end = _naive_datetime(
                appointment.scheduled_end
            )

            assignment = assignment_by_appointment.get(appointment.id)

            selected_shift = None
            required_workers = 1

            if assignment:
                selected_shift = shifts_by_id.get(assignment.shift_id)
                required_workers = assignment.workers
            else:
                unassigned_count += 1

                requirement = requirement_by_shipment.get(
                    appointment.shipment_id
                )

                required_workers = (
                    requirement.required_workers if requirement else 1
                )

                # Legacy records have no shift assignment.
                # Match them to the first shift that fully contains them.
                for shift in facility_shifts:
                    if (
                        shift.start_time <= appointment_start.time()
                        and shift.end_time >= appointment_end.time()
                        and shift.end_time > shift.start_time
                    ):
                        selected_shift = shift
                        break

            if (
                selected_shift is None
                or selected_shift.facility_id != facility_id
            ):
                continue

            if selected_shift.end_time <= selected_shift.start_time:
                continue

            # The current scheduler requires appointments to start and end
            # on the same date and fit completely inside a shift.
            shift_start = datetime.combine(
                appointment_start.date(),
                selected_shift.start_time,
            )
            shift_end = datetime.combine(
                appointment_start.date(),
                selected_shift.end_time,
            )

            overlap_start = max(appointment_start, shift_start)
            overlap_end = min(appointment_end, shift_end)

            if overlap_end > overlap_start:
                overlap_minutes = (
                    overlap_end - overlap_start
                ).total_seconds() / 60

                planned_worker_minutes += (
                    required_workers * overlap_minutes
                )

                used_shift_ids.add(selected_shift.id)

    utilization = (
        planned_worker_minutes / available_worker_minutes * 100
        if available_worker_minutes else None
    )

    return {
        "available_worker_hours": round(
            available_worker_minutes / 60, 2
        ),
        "planned_worker_hours": round(
            planned_worker_minutes / 60, 2
        ),
        "labor_utilization_percent": round(utilization, 2)
        if utilization is not None else None,
        "labor_shift_count": len(used_shift_ids),
        "scheduled_appointment_count": len(appointments),
        "unassigned_appointment_count": unassigned_count,
    }
