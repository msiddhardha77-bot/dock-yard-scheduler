# DockFlow Final Submission Checklist

Audit date: 2026-11-01

## Audit scope

This was a read-only audit. No database, schema, migration, manifest, report,
application workflow, or generated dataset was modified. Queries against the
current database used SQLite read-only mode. The accepted historical checksum
was not treated as recovered.

## Requirement status

| Original requirement | Status | Evidence and finding | Remaining action |
|---|---|---|---|
| 10 facilities | PASS | Read-only query of `full_dataset_corrected.db`: `facilities=10`; manifest and validation summary agree. | None. |
| 100 docks | PASS | Read-only count: `docks=100`; model/schema tests pass. | None. |
| Yard slots | PASS | Read-only count: `yard_slots=100`; facility/code uniqueness and FK checks pass. | None. |
| Carriers and vehicles | PASS | Read-only counts: `carriers=20`, `vehicles=60`; shipment carrier/vehicle references have zero missing parents. | None. |
| 20,000 appointments and shipments | PASS | Read-only counts: `appointments=20,000`, `shipments=20,000`, `handling_requirements=20,000`, `appointment_timelines=20,000`. | None. |
| Labor shifts and assignments | PARTIAL | Current operational snapshot has 21 shifts and 19,947 assignments; historical generated manifest has 21 shifts and 19,948 assignments. The full historical validation summary passes its expected counts. | Disclose the current departed appointment's released assignment and the historical/current distinction. |
| Approximately 100,000 lifecycle events over the target horizon | PARTIAL | Historical/full manifest: 100,000 events. Current database: 100,005. Current event timestamps extend through 2026-11-01 because of later operational activity; generated appointment requests span 2026-08-26 through 2026-10-19 (about 54.6 days), although the generator target is a 60-day horizon. | Disclose that 60 days is the generation capacity/horizon, not an observed 60-day populated span. |
| Difference between 100,000 and 100,005 events explained | PASS | The five extra current events are the later check-in, dock assignment, service start, service completion, and checkout transitions for `APPT-2026-000001`, which is now `DEPARTED`. | None; preserve both historical and current values. |
| Required ID formats | PARTIAL | Examples in current data are `FAC-001`, `DOCK-FAC-001-001`, `SHP-2026-000001`, and `APPT-2026-000001`; uniqueness checks pass. `generator/ids.py` contains an unused `APT-` helper that does not match the observed `APPT-` records. | Standardize or document the unused helper before claiming generator-wide ID-format conformance. |
| Cross-file references | PASS | Internal database FK check returned zero violations; ground-truth label-to-record coverage mismatch is zero; `submission_exports_2026-11-01/export_validation.json` records zero CSV cross-file and ground-truth reference violations. | None. |
| All required data dictionary definitions | PASS | `docs/data_dictionary.md` now provides field-level type, required/optional, allowed-value, unit, uniqueness, validation, FK and cardinality documentation for all 24 current model tables, including the requested entities and bridge/event tables. Effective-date limitations are explicitly documented. | None; retain the stated limitation that no generic master effective-date columns exist. |
| PKs, FKs and uniqueness | PASS | SQLAlchemy/schema verification previously passed for 24 tables, columns, PKs, FKs and 23 indexes. Read-only duplicate checks for key business references returned zero. | None. |
| 1:1, 1:N, bridge, optional relationships and effective dates | PARTIAL | `uselist=False`, unique constraints, FKs, reservations, assignments, timelines and nullable lifecycle fields are implemented and tested. No explicit effective-date columns exist for master relationships; there are no bridge-table effective periods beyond reservation timestamps. | Disclose that effective dating is represented only where timestamp fields exist, not as a general master-data feature. |
| Dock capacity overlap | PASS | Validation summary records exactly one intentional labelled overlap; scheduler and acceptance tests pass. |
| Incompatible load anomaly | PASS | Ground truth contains one `INCOMPATIBLE_LOAD_ASSIGNMENT`; validation confirms special handling on a general dock as intentional evidence. |
| Check-in before appointment date anomaly | PASS | Ground truth contains one `CHECK_IN_BEFORE_APPOINTMENT_DATE`; check-in outcome and anomaly evaluator cover it. |
| Labor unavailable anomaly | PASS | Ground truth contains one `LABOR_UNAVAILABLE`; validation confirms the dedicated shift over-capacity evidence. |
| No-show not recorded anomaly | PASS | Ground truth contains one `NO_SHOW_NOT_RECORDED`; validation confirms the missing no-show event is intentional. |
| Ground truth separate from input features | PASS | `anomaly_labels` and `ground_truth_records` are separate tables; current counts are 20,000 each and label coverage mismatch is zero. Generator suppresses operational exception creation for synthetic labels. |
| Derived values and lifecycle/date ordering | PASS | Read-only checks found zero invalid interval orders, zero lifecycle timestamp reversals, zero duplicate appointment/shipment/check-in references, and zero missing internal references. Acceptance tests cover timeline and reconciliation rules. |
| Arithmetic reconciliation | PASS | Historical validation summary has zero failed checks; accepted decision counts reconcile to 19,948 accepted and 52 rejected. Current raw status counts are 19,947 scheduled, 1 departed, and 52 rejected. |
| CSV exports | PASS | `submission_exports_2026-11-01/` contains 24 CSV tables. `export_validation.json` confirms manifest row counts and zero CSV primary-key duplicates. | None. |
| JSON exports | PASS | The submission directory contains `ground_truth.json`, `source_manifest.json`, `validation_summary.json`, and `export_validation.json`; ground truth has 20,000 rows and zero invalid appointment references. | None. |
| SQL export | PASS | `database/schema.sql` is standalone SQLite DDL and prior metadata comparison passed for 24 tables and 23 indexes. | None. |
| Dock utilization | PARTIAL | Runtime formula is documented in `docs/metrics.md`; isolated boundary/overlap tests pass and current value is 25.10%. Historical validation records 25.08% using 1,324,170 versus current 1,325,084 occupied minutes. | Disclose the historical/current formula-result difference; do not present 25.10% as the historical acceptance value. |
| Waiting time | PASS | `timeline_metrics()` and acceptance/integration tests calculate wait from actual arrival to service start; historical summary reports 10 minutes. | None. |
| Throughput | PASS | `app/services/metrics.py::throughput_metrics()` counts terminal `COMPLETED`/`DEPARTED` timestamps, with daily/facility buckets; tests pass. Current throughput is 1 departed and 0 completed. | None. |
| Rejection and exception causes | PASS | Scheduler cause mapping and deduplication tests pass. Current database has 1 actual `LATE_ARRIVAL` exception, status `RESOLVED`; ground-truth labels are not counted as operational exceptions. | Disclose that the current exception is operational history, not a generated anomaly row. |
| Deterministic seed `20261022` | PASS | `docs/data_generation.md`, generator configuration and tests document the seed. An isolated full two-run verification is recorded in `FUNCTIONAL_FIX_REPORT.md`; canonical row snapshot SHA matched on both runs: `331902424245f172ab8ceb2bc59b054b2016d14e73ee5e2ce42c89e3b7f23fa8`. | Repeat only if an independently reproducible submission artifact is required; use a disposable output directory. |
| Parameterized starter/full generation | PASS | `generator.generate` supports `starter`, `medium`, and `full`; `docs/data_generation.md` documents counts and explicit database URLs. | None. |
| Regeneration twice/checksum comparison demonstrated | PASS | The two isolated full runs and matching canonical SHA are recorded in `FUNCTIONAL_FIX_REPORT.md`; starter/medium demonstrations are recorded in `docs/data_generation.md`. This does not recover the historical accepted DB SHA. | Do not overwrite any existing `.db`; optionally repeat in a newly created temporary directory. |
| Three MySQL tests | NOT VERIFIED | `tests/test_mysql_integration.py` contains connectivity, competing-booking serialization, and non-overlapping-booking tests. The suite result is `81 passed, 3 skipped` because `MYSQL_TEST_DATABASE_URL` was not configured for the exact database `dock_yard_scheduler_test`. | Provision a disposable MySQL 8 schema, set a non-committed test URL, run the explicit command below, then drop that test schema only. |
| Supplier workflow | PARTIAL | No supplier-specific route, role, authentication, or authorization exists. Appointment creation can represent a planner-entered request, but supplier ownership is not modeled as a user workflow. | Disclose as out of scope or implement only if explicitly required. |
| Planner workflow | PASS | Appointment routes and scheduler support create, schedule, reschedule, cancel, rejection reasons and audit history; web/scheduler tests cover these paths. |
| Carrier/warehouse operator workflow | PARTIAL | Gate/check-in, service progression and checkout routes exist for an operator, but there are no carrier/warehouse accounts or role controls. | Demonstrate as an operational persona, not an authenticated role. |
| Logistics analyst workflow | PASS | Dashboard, reports, simulation, metrics, validation, export tooling and historical documentation exist. | Disclose that throughput facility/day buckets are service-level outputs, not a new dashboard visualization. |
| Operations manager workflow | PASS | Dashboard, exception review/resolution, reports and health endpoints exist; actual operational exception rows drive counts. | None, subject to no-authentication limitation. |

## Current database facts

Read-only SQLite queries against `full_dataset_corrected.db` returned:

```text
SHA-256: aedad28dc9a2877a53b7458946ef56002ed46df7cc5714643163a0c4b9969526
Historical accepted SHA-256 (not matched by any current database): `2979787d6f9ec722a44f69773d4bd7b340e905e1db1e6567ebc13f11e9c0caea`
appointments: 20,000
shipments: 20,000
facilities / docks / yard slots: 10 / 100 / 100
carriers / vehicles: 20 / 60
lifecycle events: 100,005
appointment statuses: SCHEDULED 19,947; DEPARTED 1; REJECTED 52
operational exceptions: 1, RESOLVED, LATE_ARRIVAL
check-in events / gate visits / yard occupancy: 2 / 1 / 1
foreign-key violations: 0
duplicate business references checked: 0
invalid interval/date ordering checks: 0
```

The departed appointment is `APPT-2026-000001`. Its decision is
`ACCEPTED/ALLOCATED`; its lifecycle includes request, scheduling, check-in,
dock assignment, service start, service completion, and checkout. Its
resolved `LATE_ARRIVAL` exception was detected and resolved during that later
operational workflow. These facts explain the five additional lifecycle rows
and the current status/count differences without altering the historical
acceptance report.

The exact five-event reconciliation is documented in
`validation/event_count_reconciliation_2026-11-01.md`.

## Test evidence

Safe command executed:

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

Result:

```text
81 passed, 3 skipped in 25.47s
```

The skipped tests are the three guarded MySQL integration tests described
above. No destructive commands, migrations, initialization, generation, or
application workflows were run against an existing database during this audit.

## Safe MySQL verification procedure

Use a newly provisioned disposable MySQL 8 database named exactly
`dock_yard_scheduler_test`, with credentials supplied only through the current
PowerShell session or a local ignored environment file. Then run:

```powershell
$env:MYSQL_TEST_DATABASE_URL = "mysql+pymysql://<local-user>:<local-password>@localhost:3306/dock_yard_scheduler_test?charset=utf8mb4"
.\venv\Scripts\python.exe -m pytest -v --run-mysql-integration tests/test_mysql_integration.py
Remove-Item Env:MYSQL_TEST_DATABASE_URL
```

Do not place the URL in Git, do not point it at production or an accepted
database, and do not run this against `full_dataset_corrected.db`.

## Submission readiness verdict

**NOT READY for an unqualified submission claim.** The core SQLite application,
dataset counts, scheduling/lifecycle behavior, anomaly labels, metrics tests,
deterministic isolated generation, and validated export artifacts are
evidenced. The submission must disclose the current-vs-historical database
distinction, the 25.08% versus 25.10% utilization difference, the lack of
authenticated persona roles, the lack of generic effective-date columns, and
the three unverified MySQL tests.

## Exact actions before submitting the GitHub link

1. Do not modify or replace either operational database. Keep the current
   SHA-256 and historical manifest values documented as separate artifacts.
2. Review `submission_exports_2026-11-01/` and its `export_validation.json`.
   Keep or publish the export artifacts according to the submission policy;
   do not include `.db`, `.env`, credentials, `venv`, caches, or logs.
3. If MySQL evidence is required, provision the isolated test schema and run
   the three-test command above; otherwise disclose `3 skipped / not verified`.
4. Capture the optional README screenshots from the local Flask copy; no UI
   redesign is required.
5. Review the checklist and README limitations, then stage only intended source,
   documentation, schema, and test files. Inspect `git diff --cached` before any
   commit.
6. Confirm `git status --short --ignored` shows no secrets, local databases,
   virtual environment, caches, logs, or generated exports staged.
7. If the limitations are acceptable, commit and push through the normal GitHub
   workflow. No commit or push was performed by this audit.
