# DockFlow functional audit

Audit date: 2026-11-01 (Asia/Calcutta)

Scope: read-only review of the existing application, tests, historical dataset
artifacts, and current operational database. No application code, frontend,
database, manifest, or historical report was modified. No migration,
initialization, generation, reset, or application workflow was run against an
existing database.

## Executive summary

The core appointment allocator, resource validation, lifecycle transitions,
exception detector, audit events, and isolated test fixtures are implemented.
The default automated suite passes. Acceptance is not fully closed because:

1. the current corrected database is operationally mutated relative to its
   historical acceptance report;
2. there is no explicit throughput metric or throughput report;
3. congestion, incompatible loads, and labor-unavailable conditions are
   scheduling rejection outcomes/anomaly evidence, not distinct operational
   exception workflows;
4. current dock utilization is calculated consistently by the application but
   does not reproduce the historical 25.08% numerator/report;
5. the full fixed-seed acceptance result is historical evidence rather than a
   fresh, independently reproducible run in this audit; and
6. MySQL concurrency/full-scale proof remains opt-in and environment-dependent.

## Requirement-by-requirement results

### 1. Scheduling engine

| Requirement | Result | Implementation and evidence |
|---|---|---|
| Dock capacity and overlap | PASS | `app/services/capacity.py:available_dock()` checks active reservations with interval overlap; `app/services/scheduler.py:schedule_appointment()` selects active compatible docks and records `DOCK_UNAVAILABLE`. Covered by `tests/test_scheduler.py:test_overlapping_booking_is_rejected` and integration allocation tests. |
| Yard facility capacity | PASS | `yard_available()` counts overlapping active yard reservations and occupancy against `Facility.yard_capacity`. Covered by `test_facility_yard_capacity_rejects_overlapping_appointment`. |
| Yard-slot capacity | PASS | `available_yard_slot()` filters active compatible slots and compares overlapping reservation count with slot capacity. Covered by `test_scheduling_rejects_full_overlapping_yard_slot` and `test_yard_slot_capacity_allows_capacity_and_rejects_next_overlap`. |
| Labor availability | PASS | `available_labor_shift()` requires a containing shift, sufficient workers, and sums overlapping assigned/legacy required workers. Covered by labor rejection and worker-consumption tests. |
| Vehicle compatibility | PASS | `compatibility.compatible()` checks shipment direction and vehicle type; scheduler also checks shipment weight against vehicle capacity. Covered by `test_vehicle_capacity_and_outbound_dock_support_are_enforced`. |
| Handling requirements | PASS | `handles_requirement()` and `handling_yard_slot_type()` enforce refrigerated, hazardous, and combined resource types. Covered by specialized and dual-handling tests and historical five-anomaly validation. |
| Appointment time windows | PASS | Scheduler checks positive requested window, requested duration fit, same-day operating hours, and scheduled end. Covered by outside-hours and time-window scheduler tests. |
| Rejection reasons/audit | PASS | `_reject()` creates a `SchedulingDecision` with a reason code and a lifecycle event. Web tests verify rejection reason visibility and audit history. |
| Timezone/overnight robustness | PARTIAL | Datetimes are normalized to UTC in several paths, but scheduling uses local-looking `time()` comparisons and explicitly does not support overnight shifts. Facility timezone is not applied in the capacity calculation. |

### 2. Appointment lifecycle

| Requirement | Result | Implementation and evidence |
|---|---|---|
| Request and scheduling | PASS | Appointment creation route creates `REQUESTED`; scheduler creates reservations, labor assignment, accepted decision, and `SCHEDULED` event. Covered by scheduler and web tests. |
| Check-in | PASS | `app/routes/checkins.py:checkin()` rejects non-scheduled and early arrivals, writes `CheckInEvent`, `GateVisit`, `YardOccupancy`, timeline arrival, and lifecycle transition. Covered by lifecycle and early-check-in tests. |
| Loading/unloading/service progression | PARTIAL | `complete()` represents dock assignment, service start, and service completion as `AT_DOCK`, `IN_SERVICE`, and `COMPLETED`. There are no separate loading/unloading domain events or status distinctions; the workflow is a generic one-step service progression. |
| Departure/checkout | PASS | `checkout()` requires a completed appointment, closes yard occupancy, writes departure, completes active resource reservations, removes labor assignment, and appends `DEPARTED`. Covered by `test_gate_progression_and_checkout`. |
| Invalid transition protection | PASS | `lifecycle.TRANSITIONS` and `transition()` reject invalid states and out-of-order timestamps. Covered by invalid-transition and checkout-before-completion tests. |

### 3. Exception and disruption handling

| Requirement | Result | Implementation and evidence |
|---|---|---|
| No-shows | PASS | `exception_detector.detect_no_show()` marks overdue scheduled appointments `NO_SHOW`, appends an event, creates a `NO_SHOW` exception, and releases dock/yard/labor resources. Covered by two lifecycle tests and NEG-005 evaluator behavior. |
| Early arrivals | PASS | `detect_arrival()` creates `EARLY_ARRIVAL` when more than 30 minutes early; early check-in before scheduled start is separately recorded as rejected `CheckInEvent`. Covered by early-arrival/check-in tests and anomaly evidence. |
| Congestion | PARTIAL | Dock/yard/labor scarcity produces scheduling rejection reason codes such as `DOCK_UNAVAILABLE`, `YARD_CAPACITY_EXCEEDED`, and `LABOR_UNAVAILABLE`, but there is no dedicated congestion operational-exception cause, detector, or dashboard category. |
| Incompatible loads | PARTIAL | Incompatible handling is rejected or deliberately represented by `INCOMPATIBLE_LOAD_ASSIGNMENT` ground truth. It is not an operational exception path unless a separate detector creates one. |
| Labor unavailable | PARTIAL | The scheduler correctly rejects unavailable labor with `LABOR_UNAVAILABLE` and the anomaly evaluator verifies evidence. No operational exception is created for that scheduling failure. |
| Invalid appointments | PASS | Invalid status, facility/shipment mismatch, direction, weight, vehicle carrier, capacity, handling, hours, and time-window cases produce rejection decisions. Covered by scheduler tests. |
| Exception resolution | PASS | `/exceptions/<id>/resolve` updates status, resolution timestamp, and notes; lifecycle test verifies resolution. |

The important boundary is that scheduling rejection decisions and synthetic
ground-truth labels are not operational exception rows. The current design
does not promise that every rejected or labelled scenario appears in
`operational_exceptions`.

### 4. Event history and auditability

| Requirement | Result | Implementation and evidence |
|---|---|---|
| State transitions create events | PASS | Scheduling, retry, cancellation, rescheduling, check-in, dock assignment, service start/completion, checkout, and no-show paths append `LifecycleEvent` rows. Covered by lifecycle, scheduler, web, and anomaly tests. |
| Historical events are preserved on normal paths | PASS | Reschedule/cancel close resource rows and append events; tests assert ordered historical transitions. No normal service path updates prior lifecycle rows. |
| Timestamp ordering | PASS | `transition()` compares the new event timestamp to the latest event; `validation.timelines.timeline_ordered()` checks timeline order. Covered by acceptance tests. |
| Appointment relationships | PASS | Lifecycle, reservations, check-ins, timelines, decisions, and exception tables carry appointment foreign keys; model/schema inspection found all 24 tables and matching foreign keys. |
| Database-level append-only enforcement | PARTIAL | Append-only behavior is enforced by application paths and tests, not by database triggers or immutable permissions. Direct SQL/ORM mutation could still alter/delete history. |

### 5. Analytics

| Requirement | Result | Implementation and evidence |
|---|---|---|
| Dock utilization | PARTIAL | `metrics.dock_utilization_metrics()` unions actual dock-arrival-to-service-end intervals per active dock over active-dock operating capacity. Isolated test expects 9.38% and passes. Current database value is 25.10%, while the historical report says 25.08%; canonical historical SQL/numerator is not preserved. |
| Waiting time | PASS | `timeline_metrics()` calculates service start minus actual arrival and excludes missing endpoints. Acceptance test verifies 15 minutes; integration test verifies 30 minutes. |
| Throughput | FAIL | No explicit throughput metric, rate, time-bucketed throughput query, or dashboard/report field exists. `completed` is a count of `COMPLETED`/`DEPARTED`, not throughput per period. |
| Rejection counts | PASS | `evaluation_metrics()` counts accepted/rejected scheduling decisions; dashboard separately counts appointments whose current status is `REJECTED`. Documentation distinguishes these definitions. |
| Exception counts | PASS | Dashboard/evaluation metrics count actual `operational_exceptions` rows by `OPEN`/`RESOLVED`; no anomaly labels are substituted. |
| Current KPI semantics | PASS | Dashboard labels the accepted-lifecycle KPI `Accepted Appointments`; raw status chart remains `SCHEDULED=19,947`, `DEPARTED=1`, `REJECTED=52`. |

Current read-only dashboard values from the configured operational copy are:

```text
appointments:          20000
accepted appointments: 19948
raw statuses:          SCHEDULED 19947, DEPARTED 1, REJECTED 52
completed:             1
active reservations:   19947
open exceptions:       0
resolved exceptions:   1
inbound/outbound:      10000 / 10000
dock utilization:      25.10%
```

### 6. Synthetic dataset and validation

| Requirement | Result | Evidence |
|---|---|---|
| 20,000 appointment dataset | PASS | Read-only counts: `full_dataset.db` and current corrected database both contain 20,000 appointments; historical manifest targets 20,000. |
| 10 facilities / 100 docks | PASS | Read-only counts in both full database files are 10 facilities and 100 docks. |
| 100,000 lifecycle-event generation requirement | PARTIAL | `generator.generate` and `docs/data_generation.md` target five events per appointment/100,000. Historical `full_dataset.db` has 100,000. Current corrected database has 100,005 due later operational events. |
| Fixed-seed reproducibility | PARTIAL | Starter/medium reproducibility is directly exercised in `tests/test_integration_readiness.py`; historical full-run documentation reports matching runs. The original accepted full database checksum is unavailable and no fresh full regeneration was run in this audit. |
| Ground-truth labels separated | PASS | `AnomalyLabel` and `GroundTruthRecord` are distinct tables; tests verify all five issue types and truth payloads. |
| Validation/integrity checks | PASS | `validation_summary`, resource-capacity checks, timeline validation, reconciliation, scenario evaluator, and foreign-key checks are implemented. Historical validation summary reports zero failed checks. |
| No fabricated operational exceptions in generation | PASS | Generator documentation/tests distinguish anomaly labels from operational exceptions; isolated generation tests expect an empty exception distribution. |

Historical anomaly distribution contains all five labelled scenarios:

```text
DOCK_CAPACITY_EXCEEDED
INCOMPATIBLE_LOAD_ASSIGNMENT
CHECK_IN_BEFORE_APPOINTMENT_DATE
LABOR_UNAVAILABLE
NO_SHOW_NOT_RECORDED
```

### 7. Export, integration, and demonstration readiness

| Requirement | Result | Evidence |
|---|---|---|
| CSV/JSON export tooling | PASS | `generator/export.py` and `scripts/export_data.py` write model CSVs, `ground_truth.json`, `source_manifest.json`, and `validation_summary.json`. |
| SQL schema export | PASS | `database/schema.sql` is a standalone SQLite 3 DDL export; in-memory verification matches all 24 model tables, columns, PKs, FKs, and 23 indexes. |
| README/generator instructions | PASS | `README.md` and `docs/data_generation.md` document Windows setup, isolated URLs, modes, seeds, validation, and limitations. |
| Mermaid diagrams | PASS | `docs/diagrams.md` contains ER, architecture, scheduling, and exception diagrams. |
| Frontend pages | PASS | Routes/templates exist for dashboard, appointments, check-in, exceptions, reports/simulation, masters, health, and CSV export. Web tests exercise core pages and workflows. |
| Backend integration | PASS | Flask factory registers all blueprints; web tests and isolated lifecycle/scheduler tests verify route-to-service-to-model behavior. |
| MySQL proof | PARTIAL | MySQL-specific tests exist and are guarded behind `--run-mysql-integration`, but the default audit suite skips three tests because the dedicated environment is not configured. |

## Actual test evidence

Final existing suite run:

```text
73 passed, 3 skipped in 62.45s
```

The skipped tests are the opt-in MySQL integration tests. No failures occurred.

Relevant coverage includes:

- `tests/test_scheduler.py`: allocation, overlap, hours, dock/yard/labor,
  vehicle, direction, handling, cancellation, rescheduling, and audit paths.
- `tests/test_lifecycle.py`: transition protection, gate progression,
  checkout, no-show, exception resolution, resource release, early check-in.
- `tests/test_acceptance.py`: five negative scenarios, timeline validation,
  ground truth, resource validation, metrics, and read-only simulation.
- `tests/test_integration_readiness.py`: isolated generator/reproducibility,
  2,000/20,000 planning, resource integration, and utilization outcomes.
- `tests/test_web.py`: dashboard, routes, appointment workflows, rejection
  visibility, and simulation non-mutation.

Passing tests demonstrate isolated behavior; they do not prove that the
current operational database still equals the historical accepted artifact.

## Prioritized fixes

### P0 — acceptance/data integrity

1. Preserve the current operational database as an immutable snapshot and
   locate an external artifact whose SHA-256 equals the original accepted
   checksum, if historical acceptance reproducibility is required.
2. Establish a documented rule separating historical acceptance datasets from
   mutable operational/demo databases.
3. Add a full-dataset read-only acceptance checker that compares current counts,
   status distributions, event counts, exception rows, and manifest checksum
   without mutating the target.

### P1 — analytics and operational semantics

1. Define and implement throughput: numerator, denominator, reporting window,
   terminal statuses, and time bucketing.
2. Preserve the current dock-utilization formula as the canonical runtime
   formula and archive/reproduce the historical acceptance SQL separately, or
   formally retire the historical 25.08% value.
3. Decide whether congestion, incompatible loads, and labor-unavailable events
   are scheduling outcomes only or should create operational exceptions. Encode
   that decision in requirements, tests, and dashboard definitions.

### P2 — robustness and audit controls

1. Add explicit timezone/overnight-shift tests and implement facility-local
   time semantics if required by the business.
2. Add database-level protection or an archival store for immutable lifecycle
   history if direct database users are in scope.
3. Configure and run the dedicated MySQL concurrency suite; separately verify
   full-scale MySQL generation and performance.

## Recommended implementation sequence

1. Freeze and checksum the operational and historical artifacts; do not repair
   either in place.
2. Agree on the canonical acceptance database and metric definitions.
3. Add throughput requirements and tests before implementing the metric.
4. Add explicit exception semantics for congestion/resource incompatibility if
   the operational requirement expects exception rows.
5. Add full-dataset read-only regression checks and reproduce them against a
   disposable copy only.
6. Add timezone/overnight and database immutability controls if needed.
7. Configure a dedicated MySQL test schema and run concurrency/full-scale
   acceptance separately from the local SQLite demonstration environment.

## Remaining work to satisfy the original DockFlow problem statement

- Close the historical accepted-database checksum/recovery discrepancy.
- Reconcile or formally supersede the historical 25.08% dock-utilization
  result with a preserved canonical calculation.
- Define and implement throughput analytics.
- Decide and document whether resource-congestion/incompatible-load/labor
  failures are operational exceptions or scheduling decisions only.
- Complete full-scale fixed-seed acceptance validation from a verified source
  artifact, including exact event count and manifest consistency.
- Complete dedicated MySQL concurrency and full-scale validation.
- Add timezone/overnight-shift coverage if facilities can operate across dates.
