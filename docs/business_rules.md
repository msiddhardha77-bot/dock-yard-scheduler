# Business rules

- Appointments can only reserve an active compatible dock during facility operating hours.
- Shipment direction must be supported by the dock, and shipment weight must not exceed the assigned vehicle capacity.
- Reservations overlap when `existing.start < requested.end` and `existing.end > requested.start`.
- Facility yard capacity and compatible yard-slot capacity are checked for overlapping time windows before allocation.
- A labor shift must cover the entire service interval; overlapping assignments may not exceed its worker count. Existing scheduled appointments without assignment rows still consume workers using their handling requirement (or one worker by default).
- Refrigerated and hazardous handling requirements require a matching specialized dock and yard slot.
- Every accepted or rejected scheduling attempt records a decision reason and lifecycle audit event.
- Lifecycle events are append-only and invalid transitions raise an error.
- Rescheduling, cancellation, gate check-in, service progression, checkout, and no-show detection append lifecycle events.
- Cancellation and no-show detection release active dock, yard, and labor resources without deleting reservation or lifecycle history.
- Simulation is deterministic for a supplied seed and read-only; it does not persist projected appointments or events.

