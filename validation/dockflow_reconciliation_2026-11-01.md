# DockFlow final read-only reconciliation

Date: 2026-11-01 (Asia/Calcutta)

Database audited: `full_dataset_corrected.db`

This is a new reconciliation report. The database, schema, original manifest,
and `full_dataset_corrected_validation_summary.json` were not modified.

## Executive result

The current database is not byte-for-byte or row-for-row equivalent to the
database described by the original acceptance report. The original accepted
population was 20,000 appointments, 100,000 lifecycle events, 19,948 scheduled
appointments, 52 rejected appointments, and zero operational exceptions. The
current database still has 20,000 appointments, but has one departed
appointment, 19,947 scheduled appointments, one resolved exception, and
100,005 lifecycle events.

The dashboard now labels the 19,948 accepted-lifecycle KPI as **Accepted
Appointments**. The raw status chart remains database-backed and displays the
current raw statuses: 19,947 scheduled, 1 departed, and 52 rejected.

## 1. Current database facts

Read-only SQL used:

```sql
SELECT status, COUNT(*)
FROM appointments
GROUP BY status
ORDER BY status;
```

Result:

```text
DEPARTED   1
REJECTED  52
SCHEDULED 19947
```

```sql
SELECT status, COUNT(*)
FROM operational_exceptions
GROUP BY status
ORDER BY status;
```

Result:

```text
RESOLVED 1
```

```sql
SELECT COUNT(*) FROM appointments;
SELECT COUNT(*) FROM lifecycle_events;
SELECT COUNT(*) FROM operational_exceptions;
```

Result:

```text
appointments             20000
lifecycle_events         100005
operational_exceptions   1
```

## 2. Departed appointment investigation

```sql
SELECT id, reference, shipment_id, facility_id, scheduled_start,
       scheduled_end, status
FROM appointments
WHERE status = 'DEPARTED';
```

Result:

```text
id=1, reference=APPT-2026-000001, shipment_id=1, facility_id=10,
scheduled_start=2026-08-26 06:00:00, scheduled_end=2026-08-26 07:30:00,
status=DEPARTED
```

```sql
SELECT id, from_status, to_status, event_type, event_time, notes
FROM lifecycle_events
WHERE appointment_id = 1
ORDER BY event_time, id;
```

The original five generation events remain, followed by five operational
events on 2026-11-01:

```text
100001  SCHEDULED  -> CHECKED_IN  GATE_CHECK_IN
100002  CHECKED_IN -> AT_DOCK    DOCK_ASSIGNMENT
100003  AT_DOCK    -> IN_SERVICE SERVICE_START
100004  IN_SERVICE -> COMPLETED  SERVICE_COMPLETE
100005  COMPLETED  -> DEPARTED   GATE_CHECK_OUT
```

```sql
SELECT decision, reason_code, created_at, details
FROM scheduling_decisions
WHERE appointment_id = 1;
```

Result: one `ACCEPTED` decision with reason `ALLOCATED`, created on
2026-08-25. The scheduling decision was not changed; only the later lifecycle
state changed.

The associated dock reservation is also now `COMPLETED`, not `ACTIVE`.

## 3. Operational exception investigation

```sql
SELECT id, appointment_id, facility_id, severity, cause_code, description,
       detected_at, resolved_at, resolution_notes, status
FROM operational_exceptions;
```

Result:

```text
id=1, appointment_id=1, facility_id=10, severity=WARNING,
cause_code=LATE_ARRIVAL,
description='Arrival was 96687 minutes late',
detected_at=2026-11-01 09:27:07.229550,
resolved_at=2026-11-01 09:27:27.615550,
resolution_notes='Resolved by operations',
status=RESOLVED
```

The exception was created by the normal late-arrival detector during the
2026-11-01 check-in workflow and then resolved through the normal exception
route. It was not present in the original accepted report, which correctly
reported zero rows for the earlier database state.

## 4. Dock-utilization reconciliation

Historical acceptance report values:

```text
period_start           2026-08-26 00:00:00 UTC
period_end             2026-10-20 00:00:00 UTC
active_dock_count      100
available_dock_minutes 5280000
occupied_dock_minutes  1324170
dock_utilization       25.08%
```

Current application calculation from the current database:

```text
period_start           2026-08-26 00:00:00 UTC
period_end             2026-10-20 00:00:00 UTC
active_dock_count      100
available_dock_minutes 5280000
occupied_dock_minutes  1325084
dock_utilization       25.10%
```

Exact difference:

```text
1325084 - 1324170 = 914 occupied dock minutes
```

The application formula in `app/services/metrics.py` is explicitly:

```text
occupied dock minutes = sum, by dock, of the union of
actual AppointmentTimeline.dock_arrival_at -> service_end_at intervals
for ACTIVE reservations and accepted lifecycle statuses

utilization = occupied dock minutes / available active-dock operating minutes * 100
```

The denominator and reporting period agree exactly with the original report.
The 914-minute difference is therefore a numerator-method/data-state
difference, not a denominator or rounding difference. The original acceptance
report contains the result values but does not preserve its executable SQL in
the repository, so its 1,324,170-minute numerator cannot be reproduced as a
historical query from the current mutated file. The current calculation is
deterministic from current source rows and excludes the departed appointment's
completed reservation, while retaining the accepted appointments' actual
timeline intervals.

## 5. Historical report versus application metrics

| Metric | Historical report | Current database/application |
|---|---:|---:|
| Appointments | 20,000 | 20,000 |
| Scheduled raw status | 19,948 | 19,947 |
| Departed raw status | 0 | 1 |
| Rejected | 52 | 52 |
| Accepted scheduling decisions | 19,948 | 19,948 |
| Operational exceptions | 0 | 1 |
| Resolved exceptions | 0 | 1 |
| Lifecycle events | 100,000 | 100,005 |
| Available dock minutes | 5,280,000 | 5,280,000 |
| Occupied dock minutes | 1,324,170 | 1,325,084 |
| Dock utilization | 25.08% | 25.10% |

The dashboard now uses one documented utilization formula consistently and
uses actual exception rows for open/resolved counts. No records were created,
deleted, or repaired during this reconciliation.

## Remaining acceptance concerns

The database requires a separate authorized data-restoration decision if it is
expected to match the historical acceptance report again. This task did not
perform that restoration because modifying database records was explicitly
out of scope. The current dashboard truthfully reflects the current database,
while the historical acceptance report remains unchanged.
