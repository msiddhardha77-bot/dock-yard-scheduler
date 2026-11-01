# DockFlow Event Count Reconciliation

Date: 2026-11-01

## Scope

This is a read-only reconciliation of the historical generated dataset and
the current operational database. Neither database was modified.

| Source | Lifecycle events | Appointment statuses | Operational exceptions |
|---|---:|---|---:|
| Historical accepted generation report / `full_dataset.db` | 100,000 | SCHEDULED 19,948; REJECTED 52 | 0 |
| Current `full_dataset_corrected.db` | 100,005 | SCHEDULED 19,947; DEPARTED 1; REJECTED 52 | 1 resolved |

The historical generation creates five lifecycle events for appointment 1 as
part of the synthetic scheduling path. The current database retains those
100,000 historical events and adds five later operational transitions for the
same appointment. No historical rows were deleted or rewritten.

## Exact additional records

The following rows are lifecycle event IDs `100001` through `100005` in the
current database. They all belong to appointment ID `1`, reference
`APPT-2026-000001`, and occur on 2026-11-01 during the later gate/service
workflow:

| Event ID | From | To | Event type | Event time | Cause |
|---:|---|---|---|---|---|
| 100001 | `SCHEDULED` | `CHECKED_IN` | `GATE_CHECK_IN` | 09:27:07.194981 | Accepted check-in |
| 100002 | `CHECKED_IN` | `AT_DOCK` | `DOCK_ASSIGNMENT` | 09:27:10.562472 | Operator dock assignment |
| 100003 | `AT_DOCK` | `IN_SERVICE` | `SERVICE_START` | 09:27:12.812795 | Service started |
| 100004 | `IN_SERVICE` | `COMPLETED` | `SERVICE_COMPLETE` | 09:27:15.041014 | Service completed |
| 100005 | `COMPLETED` | `DEPARTED` | `GATE_CHECK_OUT` | 09:27:16.118221 | Checkout/departure |

The appointment's original scheduling decision remains `ACCEPTED` with reason
`ALLOCATED`. The current timeline contains actual arrival, dock arrival,
service start/end, and departure timestamps. The current operational database
also contains two check-in attempts, one gate visit, one yard occupancy row,
and one labor assignment fewer than the historical snapshot because checkout
released the active labor assignment.

## Related exception

The one current `operational_exceptions` row is not an additional lifecycle
event. It is a resolved `LATE_ARRIVAL` exception for appointment 1:

- detected at `2026-11-01 09:27:07.229630`;
- resolved at `2026-11-01 09:27:27.615550`;
- resolution notes: `Resolved by operations`.

The detector calculated the arrival as 96,687 minutes late relative to the
historical scheduled time. This is later operational activity, not part of the
historical generated acceptance run.

## Verification queries and result

The read-only queries used were equivalent to:

```sql
SELECT COUNT(*) FROM lifecycle_events;

SELECT id, appointment_id, from_status, to_status, event_type, event_time
FROM lifecycle_events
WHERE id > 100000
ORDER BY id;

SELECT status, COUNT(*)
FROM appointments
GROUP BY status
ORDER BY status;

SELECT id, appointment_id, cause_code, status, detected_at, resolved_at
FROM operational_exceptions;
```

Results were 100,005 total events, exactly the five rows listed above, current
statuses `DEPARTED=1`, `REJECTED=52`, `SCHEDULED=19,947`, and one resolved
`LATE_ARRIVAL` exception. The current database SHA-256 is
`aedad28dc9a2877a53b7458946ef56002ed46df7cc5714643163a0c4b9969526`; the
historical accepted SHA-256 remains unrecovered.
