STARTER = {"facilities": 2, "docks": 20, "appointments": 40}
MEDIUM = {"facilities": 10, "docks": 100, "appointments": 1000}
FULL = {"facilities": 10, "docks": 100, "appointments": 20000}

MASTER_DATA = {
    "carriers": 20,
    "vehicle_types": {
        "VAN": {"capacity_kg": 3500, "weight": 3},
        "TRUCK": {"capacity_kg": 12000, "weight": 5},
        "TRAILER": {"capacity_kg": 30000, "weight": 2},
    },
    "docks_per_facility": {
        "GENERAL": 6,
        "REFRIGERATED": 2,
        "HAZARDOUS": 2,
    },
    "yard_slots_per_facility": {
        "GENERAL": 6,
        "REFRIGERATED": 2,
        "HAZARDOUS": 2,
    },
    "appointments_per_day_per_facility": 40,
    "appointment_interval_minutes": 22,
}

# Modest differences model facility size without starving a facility over the
# 60-day horizon. Weights sum to 10 and are applied in FAC-001..FAC-010 order.
FACILITY_APPOINTMENT_WEIGHTS = (
    1.10,
    1.08,
    1.05,
    1.03,
    1.00,
    0.99,
    0.97,
    0.95,
    0.93,
    0.90,
)
