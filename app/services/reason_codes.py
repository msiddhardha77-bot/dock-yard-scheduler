REASONS = {
    "OUTSIDE_OPERATING_HOURS": "Requested service is outside the facility operating window.",
    "TIME_WINDOW_CONFLICT": "The requested duration does not fit inside the appointment window.",
    "YARD_CAPACITY_EXCEEDED": "No yard capacity is available for the requested operation.",
    "LABOR_UNAVAILABLE": "No staffed labor shift covers the requested service window.",
    "DOCK_UNAVAILABLE": "No compatible dock is available without an active reservation conflict.",
    "DOCK_INCOMPATIBLE": "Available docks do not support the direction, vehicle, or handling requirements.",
    "VEHICLE_INCOMPATIBLE": "The assigned vehicle cannot satisfy the dock or shipment requirements.",
    "VEHICLE_CAPACITY_EXCEEDED": "Shipment weight exceeds the assigned vehicle capacity.",
    "INVALID_SHIPMENT_DIRECTION": "Shipment direction must be INBOUND or OUTBOUND.",
    "INVALID_SHIPMENT_WEIGHT": "Shipment weight cannot be negative.",
    "SHIPMENT_FACILITY_MISMATCH": "Appointment and shipment must belong to the same facility.",
    "VEHICLE_CARRIER_MISMATCH": "The shipment carrier must match the vehicle carrier.",
    "INVALID_HANDLING_REQUIREMENT": "Handling worker and service requirements must be positive.",
    "HANDLING_REQUIREMENTS_INCOMPATIBLE": "No configured dock and yard slot support all required handling types.",
    "YARD_SLOT_UNAVAILABLE": "No compatible yard slot has capacity for the requested window.",
    "INVALID_STATUS": "The appointment status does not permit scheduling.",
}


def explain(code):
    return REASONS.get(code, "Scheduling request could not be fulfilled.")
