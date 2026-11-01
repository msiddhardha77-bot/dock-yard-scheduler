# DockFlow current operational snapshot

Read-only snapshot date: 2026-11-01 (Asia/Calcutta)

Database inspected: `full_dataset_corrected.db`

This snapshot is separate from and does not replace the historical manifest or
validation report. No database, schema, manifest, or historical report was
modified.

## Identity

```text
path:   D:\dock-yard-scheduler\full_dataset_corrected.db
bytes:  34816000
sha256: aedad28dc9a2877a53b7458946ef56002ed46df7cc5714643163a0c4b9969526
```

The historical accepted checksum is
`2979787d6f9ec722a44f69773d4bd7b340e905e1db1e6567ebc13f11e9c0caea` and was
not recovered. `full_dataset.db` is not treated as an accepted replacement;
it requires independent acceptance validation and has a different checksum.

## Current counts

| Table/metric | Current count/value |
|---|---:|
| facilities | 10 |
| docks | 100 |
| yard_slots | 100 |
| shipments | 20,000 |
| appointments | 20,000 |
| appointment_timelines | 20,000 |
| lifecycle_events | 100,005 |
| scheduling_decisions | 20,000 |
| dock_reservations | 19,948 |
| yard_slot_reservations | 19,948 |
| labor_assignments | 19,947 |
| anomaly_labels | 20,000 |
| ground_truth_records | 20,000 |
| operational_exceptions | 1 |

Appointment statuses:

```text
SCHEDULED  19947
DEPARTED       1
REJECTED      52
```

Scheduling decisions:

```text
ACCEPTED  19948
REJECTED     52
```

Operational exceptions:

```text
OPEN       0
RESOLVED   1
```

## Historical versus current state

The historical generation manifest and validation summary describe 100,000
lifecycle events, 19,948 scheduled appointments, and zero operational
exceptions. The current database retains 20,000 appointment rows but has five
additional operational lifecycle events, one departed appointment, one
resolved `LATE_ARRIVAL` exception, one accepted check-in, one gate visit, one
yard-occupancy row, and one fewer labor assignment.

The departed appointment is `APPT-2026-000001`. Its original scheduling
decision remains `ACCEPTED`; later operational events moved it through
`CHECKED_IN`, `AT_DOCK`, `IN_SERVICE`, `COMPLETED`, and `DEPARTED`. The
exception is associated with the same appointment and is `RESOLVED`.

## Current dashboard metrics

```text
Appointments:             20000
Accepted Appointments:    19948
Raw status chart:         SCHEDULED 19947, DEPARTED 1, REJECTED 52
Completed:                1
Active reservations:      19947
Open exceptions:          0
Resolved exceptions:      1
Inbound / outbound:       10000 / 10000
Dock utilization:         25.10%
Occupied dock minutes:    1325084
Available dock minutes:   5280000
```

Utilization uses the current application formula: union actual
`dock_arrival_at` to `service_end_at` intervals per active dock, divided by
active-dock operating capacity for the observed UTC reporting period
2026-08-26 through 2026-10-20.

## Acceptance limitation

This is an operational snapshot, not a regenerated or repaired acceptance
dataset. The original accepted database checksum could not be recovered from
the workspace, and no claim is made that the current database is identical to
the historical accepted dataset.
