# Workflow

Shipment and appointment requests enter as `REQUESTED`. The scheduler allocates a dock and records a decision, producing `SCHEDULED`. Gate operations append transitions through check-in, dock, service, completion, and departure. Exceptions are detected and resolved independently.

