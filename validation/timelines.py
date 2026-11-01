from datetime import timezone

from app.services.lifecycle import allowed_transition


TIMELINE_FIELDS = (
    "actual_arrival_at",
    "yard_entry_at",
    "dock_arrival_at",
    "service_start_at",
    "service_end_at",
    "departure_at",
)

AUDIT_ONLY_EVENT_TYPES = {
    "DOCK_ALLOCATION",
    "LABOR_CHECK",
    "YARD_CHECK",
    "CAPACITY_CHECK",
    "AUDIT_MARKER",
    "REJECTION_RECORDED",
}


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def ordered(events):
    times = [_utc(event.event_time) for event in events]
    return all(left <= right for left, right in zip(times, times[1:]))


def timeline_ordered(timeline):
    """Check populated lifecycle timestamps without fabricating missing values."""
    times = [
        _utc(getattr(timeline, field))
        for field in TIMELINE_FIELDS
        if getattr(timeline, field) is not None
    ]
    return all(left <= right for left, right in zip(times, times[1:]))


def lifecycle_history_valid(events, final_status=None):
    """Validate event ordering, transition edges, and the final appointment state."""
    events = sorted(
        events,
        key=lambda event: (_utc(event.event_time), event.id or 0),
    )
    previous_status = None
    for index, event in enumerate(events):
        if event.from_status is None:
            if index != 0 or event.to_status != "REQUESTED":
                return False
        elif event.from_status == event.to_status:
            if event.event_type not in AUDIT_ONLY_EVENT_TYPES:
                return False
        elif not allowed_transition(event.from_status, event.to_status):
            return False

        if previous_status is not None and event.from_status != previous_status:
            return False
        previous_status = event.to_status

    return final_status is None or previous_status == final_status
