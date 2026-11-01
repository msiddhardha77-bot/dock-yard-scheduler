# DockFlow Functional Fix Report

Date: 2026-11-01

## Scope and safety

This change set closes the functional gaps identified in `FUNCTIONAL_AUDIT.md`.
No accepted or operational SQLite database was modified, regenerated, migrated,
or used as a generator target. The reproducibility check used two disposable
SQLite databases in a temporary directory; the temporary output was removed
after verification. Historical manifests and validation reports were not
changed.

## Implemented changes

### Throughput

`app/services/metrics.py::throughput_metrics()` now calculates throughput from
actual terminal lifecycle data:

- `COMPLETED` uses `AppointmentTimeline.service_end_at`.
- `DEPARTED` uses `AppointmentTimeline.departure_at`.
- Missing terminal timestamps are excluded.
- Optional reporting windows are half-open (`start <= timestamp < end`).
- Results include total, completed/departed components, UTC daily buckets, and
  facility buckets.

The dashboard metrics payload now exposes `throughput_count`. The current
operational database has one departed appointment and therefore a throughput of
1; it has no completed appointments.

### Dock utilization

`dock_utilization_metrics()` now uses one documented capacity formula:

```
union of occupied dock minutes per dock
--------------------------------------- x 100
active docks x open operating minutes
```

The numerator is clipped to the reporting window and each facility's local
operating hours, and overlapping intervals on the same dock are unioned so they
are counted once. The denominator uses active docks and their available open
time. The implementation uses the facility timezone for operating-hour
boundaries. The current operational result is 1,325,084 occupied minutes /
5,280,000 available minutes = 25.10%.

The formula and the distinction between per-appointment dock time and
capacity-based utilization are documented in `docs/metrics.md`.

### Operational exceptions

`app/services/operational_exceptions.py` maps scheduling failures to meaningful
operational causes:

| Scheduling failure family | Operational cause |
|---|---|
| Dock/yard scarcity | `PEAK_CONGESTION` |
| Dock, vehicle, or handling incompatibility | `INCOMPATIBLE_LOAD` |
| Labor capacity unavailable | `LABOR_UNAVAILABLE` |
| Invalid scheduling state | `INVALID_SCHEDULING_DECISION` |

The scheduler records these rows for ordinary application scheduling failures,
deduplicates repeated failures for the same appointment and cause, and leaves
existing exception resolution fields (`status`, `resolved_at`, and
`resolution_notes`) available for traceability. Synthetic generation explicitly
suppresses operational exception creation so ground-truth labels remain
separate from operational input data.

### Reproducibility

An isolated two-run full generator verification with seed `20261022` produced:

- 10 facilities, 100 docks, 20,000 appointments, and 100,000 lifecycle events
  on each run.
- Identical generated result summaries and row counts.
- Identical canonical row snapshot SHA-256 on both runs:
  `331902424245f172ab8ceb2bc59b054b2016d14e73ee5e2ce42c89e3b7f23fa8`.
- 19,948 scheduled decisions, 52 rejected decisions, and zero generated
  operational exception rows.
- Five labelled anomaly scenarios represented in ground truth, with the normal
  scenario count 19,995 and one row for each labelled anomaly.

This verifies deterministic generation in isolated outputs. It does not make
the current operational database identical to the historical accepted
database: the historical report records 100,000 events, while the current
operational snapshot contains 100,005 events and one departed appointment plus
one resolved operational exception. No records were deleted to force the
historical count.

## Verification results

### Automated tests

- Focused functional regression tests: **40 passed**.
- Complete existing suite: **81 passed, 3 skipped**.
- New coverage is in `tests/test_metrics_and_operational_exceptions.py` and
  covers terminal throughput, daily/facility grouping, utilization clipping,
  overlap unioning, all four new exception cause families, deduplication, and
  exception resolution fields.

### MySQL concurrency validation

The three skipped tests are in `tests/test_mysql_integration.py`. They require
the environment variable `MYSQL_TEST_DATABASE_URL` with a dedicated database
whose name is `dock_yard_scheduler_test`. No such test URL was configured. A
local MySQL80 Windows service was present, but no credentials or isolated test
database were available, so concurrency and capacity enforcement remain
**unverified**, not passed.

## Remaining limitations

1. MySQL concurrency tests still require an explicitly provisioned isolated
   test database and a non-secret test URL.
2. Throughput daily and facility buckets are available through the metrics
   service; the existing frontend does not add a new visualization for those
   buckets, preserving the approved design.
3. The existing exception model provides resolution timestamps and notes, but
   there is no separate immutable exception-resolution event table.
4. The historical accepted checksum and historical 100,000-event database were
   not recovered. The current operational snapshot must not be represented as
   that accepted database.
5. Overnight operating schedules remain subject to the application's existing
   same-day operating-hours behavior and were not redesigned in this fix.

## Modified files

- `app/services/metrics.py`
- `app/services/operational_exceptions.py` (new)
- `app/services/scheduler.py`
- `generator/generate.py`
- `docs/metrics.md`
- `tests/test_metrics_and_operational_exceptions.py` (new)
- `FUNCTIONAL_FIX_REPORT.md` (new)

No database, schema, migration, historical report, manifest, or frontend design
file was modified.
