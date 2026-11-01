# DockFlow diagrams

These diagrams describe the current Flask application and SQLAlchemy models.
They are documentation only; they do not change the schema or runtime logic.

## Database ER diagram

```mermaid
erDiagram
    FACILITIES ||--o{ DOCKS : has
    FACILITIES ||--o{ YARD_ZONES : has
    FACILITIES ||--o{ YARD_SLOTS : has
    FACILITIES ||--o{ LABOR_SHIFTS : has
    FACILITIES ||--o{ SHIPMENTS : serves
    FACILITIES ||--o{ APPOINTMENTS : hosts
    CARRIERS ||--o{ VEHICLES : owns
    CARRIERS ||--o{ DRIVERS : employs
    CARRIERS ||--o{ SHIPMENTS : carries
    VEHICLES ||--o{ SHIPMENTS : transports
    SHIPMENTS ||--|| HANDLING_REQUIREMENTS : requires
    SHIPMENTS ||--o{ APPOINTMENTS : schedules
    APPOINTMENTS ||--o{ DOCK_RESERVATIONS : reserves
    DOCKS ||--o{ DOCK_RESERVATIONS : receives
    APPOINTMENTS ||--o{ YARD_SLOT_RESERVATIONS : reserves
    YARD_SLOTS ||--o{ YARD_SLOT_RESERVATIONS : receives
    LABOR_SHIFTS ||--o{ LABOR_ASSIGNMENTS : provides
    APPOINTMENTS ||--o{ LABOR_ASSIGNMENTS : uses
    APPOINTMENTS ||--o{ CHECK_IN_EVENTS : attempts
    APPOINTMENTS ||--o| GATE_VISITS : visits
    APPOINTMENTS ||--o| APPOINTMENT_TIMELINES : records
    APPOINTMENTS ||--o{ LIFECYCLE_EVENTS : audits
    APPOINTMENTS ||--o{ OPERATIONAL_EXCEPTIONS : raises
    APPOINTMENTS ||--o{ SCHEDULING_DECISIONS : receives
    APPOINTMENTS ||--o{ YARD_OCCUPANCY : occupies
    APPOINTMENTS ||--o{ ANOMALY_LABELS : labels
    APPOINTMENTS ||--o{ GROUND_TRUTH_RECORDS : evaluates
```

`SimulationRun` is a standalone seed/mode/idempotency record. `GroundTruthRecord`
and `AnomalyLabel` are evaluation artifacts; they are not scheduling inputs.

## System architecture

```mermaid
flowchart TD
    Browser[Browser] --> Flask[Flask application factory]
    Flask --> Routes[Blueprint routes]
    Routes --> Templates[Jinja templates]
    Routes --> Services[Domain services]
    Services --> Scheduler[Scheduler and capacity checks]
    Services --> Lifecycle[Lifecycle and exception services]
    Services --> Metrics[Metrics and reports]
    Services --> ORM[SQLAlchemy models]
    ORM --> DB[(SQLite or MySQL)]
    Generator[Deterministic generator] --> ORM
    Validation[Validation and scenario tools] --> ORM
    Export[CSV/JSON exporter] --> ORM
```

## Appointment scheduling workflow

```mermaid
flowchart TD
    Request[REQUESTED appointment] --> Validate[Validate facility, shipment, window, hours, vehicle, handling, yard, labor, and dock]
    Validate -->|all checks pass| Allocate[Create dock/yard/labor allocations]
    Allocate --> Accept[Record ACCEPTED decision]
    Accept --> Scheduled[SCHEDULED]
    Validate -->|any check fails| Reject[Record REJECTED decision and reason]
    Scheduled --> CheckIn[Gate check-in]
    CheckIn --> AtDock[AT_DOCK]
    AtDock --> Service[IN_SERVICE]
    Service --> Complete[COMPLETED]
    Complete --> Depart[DEPARTED]
    Scheduled --> Cancel[CANCELLED]
    Scheduled --> NoShow[NO_SHOW detection]
```

## Exception handling workflow

```mermaid
flowchart TD
    Event[Arrival or appointment-window event] --> Detector[Exception detector]
    Detector -->|threshold crossed| Create[Create OPEN operational exception]
    Detector -->|normal or intentionally undetected| NoRow[No operational exception row]
    Create --> Review[Operations reviews Exceptions page]
    Review --> Resolve[Resolve with timestamp and notes]
    Resolve --> Closed[RESOLVED]
    Create --> Dashboard[Dashboard open/resolved counts]
    Closed --> Dashboard
```
