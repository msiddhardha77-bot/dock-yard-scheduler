# Cardinality and lifecycle

Each appointment references one shipment and facility, has many historical dock and yard-slot reservations with at most one active reservation per resource/time interval, many check-in attempts and lifecycle events, one optional timeline, and zero or many exceptions. Reservation cancellation/rescheduling closes the prior row and creates a new row; it does not overwrite history. Events are append-only. Valid states and transitions are defined in `app/services/lifecycle.py`.
