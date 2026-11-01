"""Deterministic, labelled negative scenarios kept separate from baseline data."""

SCENARIOS = [
    {"scenario_id": "NEG-001", "issue_type": "DOCK_CAPACITY_EXCEEDED", "expected_reason_code": "DOCK_UNAVAILABLE"},
    {"scenario_id": "NEG-002", "issue_type": "INCOMPATIBLE_LOAD_ASSIGNMENT", "expected_reason_code": "DOCK_INCOMPATIBLE"},
    {"scenario_id": "NEG-003", "issue_type": "CHECK_IN_BEFORE_APPOINTMENT_DATE", "expected_reason_code": "EARLY_CHECK_IN"},
    {"scenario_id": "NEG-004", "issue_type": "LABOR_UNAVAILABLE", "expected_reason_code": "LABOR_UNAVAILABLE"},
    {"scenario_id": "NEG-005", "issue_type": "NO_SHOW_NOT_RECORDED", "expected_reason_code": "NO_SHOW"},
]


def scenario_manifest(results=None):
    results = results or {}
    return [{**scenario, **results.get(scenario["scenario_id"], {})} for scenario in SCENARIOS]
