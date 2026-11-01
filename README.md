# DockFlow

DockFlow is a Flask and SQLAlchemy application for traceable dock appointment
scheduling. It coordinates docks, yard slots, labor shifts, vehicle capacity,
handling requirements, gate operations, lifecycle history, exceptions, and
operational reports.

This repository contains the application and deterministic synthetic-data
generation/validation tooling. It is a demonstration and evaluation system; it
does not provide authentication, authorization, or a production deployment
configuration.

## Business problem and objectives

Inbound and outbound loads compete for finite dock, yard, labor, and operating-
hour capacity. A valid booking must fit the requested window, use compatible
resources, respect overlapping reservations and capacity, and leave an audit
trail when it is accepted or rejected.

DockFlow objectives are to:

- allocate appointments deterministically and explain rejection reasons;
- prevent dock, yard-slot, labor, vehicle, and handling conflicts;
- preserve scheduling and operational history through append-only events;
- support gate check-in through service completion and checkout;
- expose database-backed metrics, exceptions, reports, and exports; and
- validate generated datasets with integrity, anomaly, capacity, and
  reproducibility checks.

## Main features

- Appointment creation, detail, filtering, rescheduling, and cancellation.
- Inbound/outbound allocation with dock direction and vehicle compatibility.
- Operating-hours, requested-window, dock-overlap, yard, labor, vehicle-payload,
  refrigerated, and hazardous-handling validation.
- Accepted/rejected scheduling decisions with reason codes and lifecycle audit.
- Gate check-in, dock assignment, service start/completion, checkout, and
  no-show detection.
- Resource release on cancellation, no-show, and checkout while retaining
  historical reservations.
- Exception review and resolution.
- Dashboard and report metrics, timeline-derived measurements, and CSV export.
- Read-only deterministic appointment simulation.
- Starter, medium, and full deterministic synthetic data generation,
  anomaly labels, ground truth, validation, and export.

## User roles

There is no login or role-enforcement layer. The following are operational
personas for demonstration and testing, not application security roles:

| Persona | Typical use |
|---|---|
| Planner | Create, schedule, reschedule, cancel, and review appointments. |
| Gate operator | Check vehicles in, advance dock/service state, and check out. |
| Operations supervisor | Review dashboard metrics, reports, capacity, and exceptions. |
| Data/evaluation engineer | Generate, export, validate, and compare synthetic datasets. |
| Developer | Run Flask locally, isolated fixtures, and regression tests. |

## Technology stack

- Python 3.11-compatible environment
- Flask application factory
- Flask-SQLAlchemy and SQLAlchemy ORM
- Flask-Migrate/Alembic migration support
- SQLite for local/demo and test databases
- MySQL 8 with PyMySQL support
- Jinja templates, Bootstrap-style CSS, Bootstrap Icons, and Chart.js
- pytest, Faker, pandas, and NumPy for testing and data tooling

## System architecture

The application factory in `app/__init__.py` configures the database and
registers route blueprints. Routes handle HTTP concerns, services implement
scheduling/capacity/lifecycle/exception/metric logic, models define persistence,
and generator/validation modules operate on explicit database URLs. See the
[architecture diagram](docs/diagrams.md#system-architecture).

## Database entities and relationships

Master data includes facilities, docks, yard zones/slots, carriers, vehicles,
drivers, labor shifts, and labor assignments. Operational data includes
shipments, appointments, reservations, check-in events, gate visits, timelines,
and yard occupancy. Scheduling decisions, lifecycle events, operational
exceptions, simulation runs, anomaly labels, and ground-truth records provide
audit/evaluation data. See the [ER diagram](docs/diagrams.md#database-er-diagram)
and [data dictionary](docs/data_dictionary.md).

## Appointment scheduling workflow

Requests enter as `REQUESTED`. The scheduler validates the shipment/facility
relationship, requested window, operating hours, vehicle payload, handling
requirements, yard capacity, labor, yard slot, dock compatibility, and active
dock overlap. A successful allocation creates reservations, labor assignment,
an `ACCEPTED` decision, and a `SCHEDULED` event. A failed allocation records a
`REJECTED` decision and reason. Gate operations append the subsequent lifecycle
events. See the [scheduling workflow diagram](docs/diagrams.md#appointment-scheduling-workflow).

## Capacity validation

- **Dock:** active compatible dock, direction and vehicle type, handling type,
  operating hours, and non-overlapping active reservations.
- **Yard:** facility capacity and a compatible yard slot over the appointment
  interval.
- **Labor:** a shift that covers the service interval without exceeding worker
  capacity; legacy scheduled rows can use handling requirements as fallback.
- **Vehicle:** shipment weight must not exceed the linked vehicle capacity.

The validation package also checks generated resource relationships, deliberate
negative scenarios, timeline ordering, foreign keys, anomaly evidence, and
reproducibility.

## Exception management

Operational exceptions are stored in `operational_exceptions` and are counted
directly from that table. The current detector supports late-arrival and no-show
workflows. Exceptions can be reviewed and resolved through the Exceptions page;
resolution records status, timestamp, and notes. Synthetic anomaly labels are
evaluation evidence and are not operational exception rows.

See the [exception workflow diagram](docs/diagrams.md#exception-handling-workflow).

## Dataset generation and validation

`generator.generate` supports `starter`, `medium`, and `full` modes. The target
full profile is 10 facilities, 100 docks, 100 yard slots, 20,000 appointments,
20,000 timelines, and 100,000 generated lifecycle events. Use a separate
database URL for generation; never point generation or schema initialization at
an accepted baseline.

The validation package checks integrity, capacity, lifecycle/timeline rules,
scenario outcomes, anomaly/ground-truth consistency, and reproducibility.
Exports are produced by `scripts/export_data.py`.

## Windows installation and setup

From PowerShell:

```powershell
cd D:\dock-yard-scheduler
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The repository currently has a local virtual environment at `venv`. If using
it, activate it instead of creating another environment.

## Environment configuration

`.env` is local-only and ignored by Git. Relevant settings are:

```dotenv
DATABASE_URL=sqlite:///D:/dock-yard-scheduler/full_dataset_corrected.local.db
SECRET_KEY=replace-with-a-local-random-secret
APP_TIMEZONE=Asia/Calcutta
ITEMS_PER_PAGE=25
```

For MySQL 8, use a local URL such as
`mysql+pymysql://user:password@localhost:3306/database?charset=utf8mb4`.
Do not commit credentials. `MYSQL_TEST_DATABASE_URL` is reserved for the
explicitly opt-in dedicated MySQL integration tests.

The accepted baseline is `full_dataset_corrected.db`; it is protected and must
not receive `flask init-db`, migrations, generation, or application writes.
Local development uses the separate `full_dataset_corrected.local.db` copy.

## Run the Flask application

```powershell
.\venv\Scripts\Activate.ps1
$env:FLASK_APP = "run.py"
flask run
```

Open `http://127.0.0.1:5000/`. The dashboard is also available at
`/dashboard`. Health endpoints are `/health` and `/health/db`.

`flask init-db` is only for a fresh/local working database. Never run it
against `full_dataset_corrected.db`.

## Generate isolated data

Always provide a separate output database URL:

```powershell
python -m generator.generate --mode starter --seed 20261022 `
  --database-url sqlite:///D:/dock-yard-scheduler/output/starter.db
python -m generator.generate --mode full --seed 20261022 `
  --database-url sqlite:///D:/dock-yard-scheduler/output/full.db
```

Run the negative-scenario evaluator with an isolated database:

```powershell
python -m validation.scenario_evaluator `
  --database-url sqlite:///D:/dock-yard-scheduler/output/scenarios.db `
  --output D:/dock-yard-scheduler/output/scenario_results.json
```

## Run tests

```powershell
pytest -q
python -m compileall -q app generator validation scripts config.py run.py
```

The default suite uses isolated SQLite fixtures. MySQL integration tests are
skipped unless explicitly authorized and pointed at the dedicated test schema:

```powershell
$env:MYSQL_TEST_DATABASE_URL = "mysql+pymysql://user:password@localhost:3306/dock_yard_scheduler_test?charset=utf8mb4"
pytest -v --run-mysql-integration tests/test_mysql_integration.py
```

## Screenshots

No screenshots are stored in this repository. Capture presentation screenshots
from the local Flask server after setup. Suggested captures are:

1. Dashboard overview and status chart.
2. Appointment list/detail with scheduling decision and lifecycle history.
3. Gate management timeline.
4. Exception review page.
5. Reports and simulation output.

## Project deliverables and known limitations

Deliverables include the Flask application, SQLAlchemy models, standalone
SQLite DDL in `database/schema.sql`, deterministic generator, validation and
scenario tools, CSV/JSON export tooling, source manifests, validation
summaries, README documentation, and Mermaid diagrams.

Dataset versions must be distinguished:

- The historical accepted generation report describes 10 facilities, 100
  docks, 20,000 appointments, and 100,000 lifecycle events.
- The current operational `full_dataset_corrected.db` contains 20,000
  appointments and 100,005 lifecycle events after later operational workflow
  activity. Its current SHA-256 is recorded in
  `validation/current_operational_snapshot_2026-11-01.md`.
- The original accepted database checksum could not be recovered. Neither
  `full_dataset.db` nor the current corrected database is claimed as an
  accepted replacement without independent validation.

Known limitations are the absence of authentication/authorization, labor-hours
utilization not being exposed as a dashboard metric, and MySQL
concurrency/full-scale acceptance requiring a dedicated configured MySQL test
environment.

## Documentation index

- [Architecture](docs/architecture.md)
- [Business rules](docs/business_rules.md)
- [Workflow](docs/workflow.md)
- [Database diagrams](docs/diagrams.md)
- [Data dictionary](docs/data_dictionary.md)
- [Metrics](docs/metrics.md)
- [Dataset generation](docs/data_generation.md)
- [Testing](docs/test_plan.md)
- [Requirements traceability](docs/requirements_traceability.md)
- [Acceptance history](docs/acceptance_report.md)
