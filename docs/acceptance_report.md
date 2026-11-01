# Acceptance report

| Criterion | Test performed | Expected | Actual | Result |
|---|---|---|---|---|
| Application health | Live Flask request to `/health` | HTTP 200 | HTTP 200 | PASS |
| Core web routes | Live requests to dashboard, appointments, reports, check-in, exceptions | HTTP 200 | HTTP 200 | PASS |
| Appointment workflow | Flask integration test | Create, view, filter, reschedule, cancel | Passed | PASS |
| Scheduling constraints | Unit tests | Reject overlap, bad hours, dock, labor, yard cases | Passed | PASS |
| Lifecycle and gate | Integration tests | Check-in → dock → service → completion → departure | Passed | PASS |
| No-show/exception | Integration test | Detect and resolve exception | Passed | PASS |
| Starter dataset | Isolated SQLite run | 2 facilities, 20 docks, 40 appointments | Verified previously and documented | PASS |
| Full dataset | Isolated SQLite run | 10 facilities, 100 docks, 20,000 appointments, 100,000 events | Verified previously and documented | PASS |
| Reproducibility | Two isolated fixed-seed databases | Canonical hashes match | Hashes matched | PASS |
| Export deliverables | `python scripts/export_data.py --output ...` | CSV/JSON/manifest output | Full isolated export produced all entity CSVs, ground truth, validation summary, and README | PASS |
| MySQL integration | Real MySQL connection | Successful schema and concurrency test | No configured server/credentials | BLOCKED |
| MySQL readiness | Configuration and guarded integration tests | Safe URL handling, schema init path, connectivity probe | `.env` absent; `/health/db` and opt-in test module implemented; authenticated run not attempted | PARTIAL |
| MySQL starter population | In-context dialect probe and existing starter generator | Populate exact starter counts without reset | MySQL confirmed; generator completed in 2.37 seconds with 2/20/20/40/40/80 requested counts | PASS |
| MySQL read-only application checks | Flask test client using configured MySQL | Core routes and database health respond | All checked routes returned HTTP 200 | PASS |
| MySQL concurrent booking | Opt-in `tests/test_mysql_integration.py` | Separate MySQL sessions prevent double booking | Not run because dedicated `MYSQL_TEST_DATABASE_URL` was not configured; main DB was not used for mutation | BLOCKED |
| MySQL integration rerun | `pytest -v tests/test_mysql_integration.py` | Two tests execute only against `dock_yard_scheduler_test` | 2 skipped because the dedicated URL is absent | BLOCKED |
| Full negative scenario evaluation | `python -m validation.scenario_evaluator ...` | Five scenario results with actual outcomes | 5/5 passed: overlap, incompatibility, early check-in, labor shortage, missing no-show detection | PASS |
| Full handling/yard generation | Full isolated generator | Yard slots and special handling records linked to parents | 100 yard slots, 20,000 handling requirements, 2,000 refrigerated, 1,000 hazardous, zero orphan timelines | PASS |
| Metric source fields | Full isolated timeline query | Event-derived durations and waits | Average wait 10.0 minutes; dock occupied 1,120,240 minutes; yard occupied 1,315,160 minutes | PASS |
| Automated regression suite | `pytest -v` | All focused tests pass | 17 passed | PASS |
| MySQL full-scale generation | Dedicated `dock_yard_scheduler_full_test` only | 10 facilities, 100 docks, 20,000 appointments, 100,000 lifecycle events | Blocked before generation: `dockyard_app` lacks permission to create/access the dedicated database (MySQL error 1044) | BLOCKED |
| MySQL full-scale generation retry | Guarded full generator with seed `20261022` | Required full-scale counts and validations | Preflight passed, but generation stopped after approximately 101 seconds with MySQL error 1114 (`appointments` table full); MySQL80 subsequently stopped and could not be restarted from this session | BLOCKED |

## 2026-10-31 application functionality verification

| Criterion | Test performed | Expected | Actual | Result |
|---|---|---|---|---|
| Baseline app regression | `pytest -q -ra` using isolated fixtures and default MySQL integration opt-in gate | No failures; integration tests skipped unless explicitly enabled | 48 passed, 3 skipped | PASS |
| Compilation | `compileall` for `app`, `generator`, `validation`, `scripts`, and `tests` | All Python files compile | Passed | PASS |
| Live main DB identity | Read-only connection derived from `DATABASE_URL` | Active schema exactly `dock_yard_scheduler` | `dock_yard_scheduler` | PASS |
| Main starter data preservation | Read-only counts before and after route/simulation GETs | Counts unchanged | 2 facilities, 20 docks, 41 appointments, 85 lifecycle events, 1 simulation run before and after | PASS |
| Read-only live routes | Flask test client GETs | All checked pages/exports return 200 | `/health`, `/health/db`, dashboard, appointment list, reports, CSV, simulation, check-ins, exceptions, masters all returned 200 | PASS |
| Appointment creation and validation | Isolated Flask integration tests | Valid request schedules; incompatible resources reject with reason | Tests pass; rejection reason is displayed and recorded in decision/audit history | PASS |
| Inbound/outbound | Isolated scheduling and direction-filter tests | Direction-specific dock eligibility and filtering | Inbound/outbound allocation and filters verified | PASS |
| Dock, yard, labor, vehicle constraints | Isolated scheduler tests | Overlap, slot capacity, worker capacity, payload, hours, compatibility enforced | 11 scheduler tests pass, including legacy labor fallback | PASS |
| Lifecycle and resource release | Isolated lifecycle tests | Auditable scheduling, reschedule, cancel, check-in, service, checkout, no-show | 6 lifecycle tests pass; no-show releases dock/yard/labor resources | PASS |
| Reporting and simulation | Read-only live starter query and isolated web test | Deterministic output and no record mutation | Seed 20261022: 41 total, 34 scheduled, 39 projected, 2,951 projected service minutes, 75.67 average, 39/39 within window; main row counts unchanged | PASS |
| Full-scale MySQL acceptance | Dedicated `dock_yard_scheduler_full_test` | 10/100/20,000/100,000 rows, integrity, reproducibility, performance | Not run; remains a separate final acceptance task | NOT RUN |
| MySQL integration-test schema side effect | Read-only inspection after an earlier unguarded pytest run | Dedicated test schema isolated | Current observed `dock_yard_scheduler_test`: 16 facilities, 16 docks, 32 appointments, 12 lifecycle events; 32 appointment refs match `MYSQL-A-*`/`MYSQL-NA-*`. No prior baseline is available to determine the exact delta; no cleanup performed. Default suite now skips these tests unless `--run-mysql-integration` is supplied. | REVIEW |

No database reset/generation, `.env` edit, or GitHub push was performed during this application completion pass. The main database was used only for SELECTs and GET requests.
