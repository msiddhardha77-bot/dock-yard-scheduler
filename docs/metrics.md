# Metrics

Dashboard and report metrics are calculated from stored appointments,
scheduling decisions, reservations, timelines, and operational exceptions.
CSV export is query-backed and does not fabricate records. The simulation
endpoint is a deterministic projection and does not write appointments or
events.

| Metric | Formula | Scope |
|---|---|---|
| Acceptance rate | accepted scheduling decisions / all accepted and rejected scheduling decisions | decision history in the selected database |
| Rejection rate | rejected scheduling decisions / all accepted and rejected scheduling decisions | decision history in the selected database |
| Dock utilization | union of actual dock-arrival-to-service-end time / active dock open-hours capacity × 100 | whole UTC calendar days containing observed dock activity, clipped to each facility's local operating hours |
| Inbound/outbound count | appointment count grouped by linked shipment direction | selected database population |
| Completed count | appointments in `COMPLETED` or `DEPARTED` | selected database population |
| No-show rate | `NO_SHOW` appointments / all appointments | selected database population |
| Exception rate | all exception rows / all appointments | selected database population |

`evaluation_metrics()` derives acceptance/rejection rates from
`SchedulingDecision`, rather than treating canceled or in-progress appointments
as accepted outcomes. `dock_utilization_metrics(start_at, end_at)` can be
scoped to an explicit UTC reporting window; if omitted, it uses whole UTC
calendar days containing recorded dock activity. Its numerator unions actual
dock-arrival-to-service-end intervals by active dock and excludes canceled,
rejected, and no-show appointments. Its denominator is active docks multiplied
by each facility's available open time in the window. If there are no observed
intervals or no available dock time, utilization is reported as unavailable
rather than a misleading zero.

`AppointmentTimeline` and `YardSlotReservation` store actual arrival, yard,
dock, service, and departure timestamps. `timeline_metrics()` calculates
average wait as service start minus actual arrival, per-appointment dock time
as service end minus dock arrival, and occupied yard time as departure minus
yard entry. Rows missing either endpoint are excluded; no values are
fabricated. Per-appointment dock minutes can count overlapping appointments
separately; use the union-based `dock_utilization_metrics()` result for
resource-capacity utilization. Labor assignments enforce overlapping worker
capacity, but a historical labor-hours utilization metric is not exposed yet.

`simulate_appointments(seed)` projects deterministic bounded service durations
for currently active scheduled/in-service appointments. It reports projection
count, projected service minutes, average projected duration, in-window
count/rate, and rejection reasons. Canceled, rejected, and no-show appointments
are excluded from projections. The `/reports/simulation?seed=20261022` endpoint
is read-only.

Measured against the configured starter database on 2026-10-31: 41
appointments, 34 currently scheduled, 39 projected appointments, 2,951
projected service minutes, 75.67 average projected minutes, and all 39
projected completions within their requested windows. The simulation was
repeated with the same seed and did not change database counts.

## Current operational snapshot

The current operational database is `full_dataset_corrected.db` (local
development uses its separate `.local.db` copy). It is not identical to the
historical accepted dataset; see the [current operational snapshot](../validation/current_operational_snapshot_2026-11-01.md).

Current dashboard definitions and values are:

| Dashboard item | Definition | Current value |
|---|---|---:|
| Appointments | `COUNT(*)` from `appointments` | 20,000 |
| Accepted Appointments | appointments in the accepted lifecycle set: `SCHEDULED`, `CHECKED_IN`, `AT_DOCK`, `IN_SERVICE`, `COMPLETED`, `DEPARTED` | 19,948 |
| Raw status chart | `COUNT(*)` grouped by stored `appointments.status` | `SCHEDULED` 19,947; `DEPARTED` 1; `REJECTED` 52 |
| Rejected | appointments whose stored status is `REJECTED` | 52 |
| Completed | appointments whose stored status is `COMPLETED` or `DEPARTED` | 1 |
| Active reservations | `dock_reservations.status = 'ACTIVE'` | 19,947 |
| Open exceptions | `operational_exceptions.status = 'OPEN'` | 0 |
| Resolved exceptions | `operational_exceptions.status = 'RESOLVED'` | 1 |
| Dock utilization | union of actual dock-arrival-to-service-end intervals by active dock divided by active-dock operating capacity | 25.10% |

The Accepted Appointments KPI is intentionally distinct from both raw status
counts and scheduling decisions. The scheduling-decision counts are read from
`scheduling_decisions`: current `ACCEPTED=19,948` and `REJECTED=52`. A decision
is an allocation/audit outcome; an appointment status is its current lifecycle
state. A departed appointment therefore remains in the accepted KPI while the
raw chart continues to show `DEPARTED`.

For the current utilization value, the numerator is 1,325,084 occupied dock
minutes, the denominator is 5,280,000 available dock minutes, and the reporting
period is 2026-08-26 00:00 UTC through 2026-10-20 00:00 UTC. These values are
calculated from current source rows and must not be substituted with historical
acceptance-report values.
