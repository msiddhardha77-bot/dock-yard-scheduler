"""Execute the five deliberately isolated negative scenarios against real services."""
import argparse
import json
from datetime import datetime, timedelta, timezone, time
from pathlib import Path

from app import create_app, db
from app.models.domain import CheckInEvent, YardSlot
from app.models.events import OperationalException
from app.models.masters import Carrier, Dock, Facility, LaborShift, Vehicle
from app.models.operations import Appointment, Shipment
from app.models.scheduling import SchedulingDecision
from app.services.scheduler import schedule_appointment
from config import Config


def _case(code, start=None, dock_type="GENERAL", vehicle_type="TRUCK", workers=5):
    facility = Facility(code=code, name=f"Scenario {code}", yard_capacity=10)
    carrier = Carrier(code=f"C-{code}", name="Scenario Carrier")
    db.session.add_all([facility, carrier]); db.session.flush()
    db.session.add_all([Dock(facility_id=facility.id, code=f"DOCK-{code}-001", dock_type=dock_type, vehicle_types="VAN" if vehicle_type == "TRUCK" and dock_type == "INCOMPATIBLE" else "TRUCK"),
                        LaborShift(facility_id=facility.id, name="Scenario shift", start_time=time(0), end_time=time(23, 59), workers=workers),
                        YardSlot(facility_id=facility.id, code=f"YARD-{code}-001", capacity=5)])
    vehicle = Vehicle(carrier_id=carrier.id, registration=f"TRK-{code}", vehicle_type=vehicle_type)
    db.session.add(vehicle); db.session.flush()
    start = start or (
        (datetime.now(timezone.utc) + timedelta(days=1))
        .replace(hour=10, minute=0, second=0, microsecond=0)
    )
    shipment = Shipment(reference=f"SHP-{code}", facility_id=facility.id, carrier_id=carrier.id, vehicle_id=vehicle.id, direction="INBOUND", weight_kg=1000)
    db.session.add(shipment); db.session.flush()
    appointment = Appointment(reference=f"APT-{code}", shipment_id=shipment.id, facility_id=facility.id,
                              requested_start=start, requested_end=start + timedelta(hours=2), duration_minutes=60)
    db.session.add(appointment); db.session.commit()
    return facility, appointment


def evaluate(database_url):
    ScenarioConfig = type("ScenarioConfig", (Config,), {"SQLALCHEMY_DATABASE_URI": database_url, "TESTING": True})
    app = create_app(ScenarioConfig)
    with app.app_context():
        db.create_all()
        results = []

        facility, first = _case("NEG01")
        first_result = schedule_appointment(first)
        second_facility, second = _case("NEG02A")
        # Place the second appointment on the first facility/dock at the same time.
        second.facility_id = facility.id; second.shipment.facility_id = facility.id
        second.requested_start = first.requested_start; second.requested_end = first.requested_end; db.session.commit()
        second_result = schedule_appointment(second)
        decision = SchedulingDecision.query.filter_by(appointment_id=second.id).order_by(SchedulingDecision.id.desc()).first()
        results.append({"scenario_id": "NEG-001", "issue_type": "DOCK_CAPACITY_EXCEEDED", "entity_ids": {"first_appointment": first.id, "second_appointment": second.id},
                        "expected": "REJECTED", "actual": second.status, "expected_code": "DOCK_UNAVAILABLE", "actual_code": decision.reason_code if decision else None,
                        "pass": first_result is not None and second_result is None and second.status == "REJECTED"
                        and decision is not None and decision.reason_code == "DOCK_UNAVAILABLE"})

        _, incompatible = _case("NEG02", dock_type="INCOMPATIBLE")
        incompatible_result = schedule_appointment(incompatible)
        decision = SchedulingDecision.query.filter_by(appointment_id=incompatible.id).order_by(SchedulingDecision.id.desc()).first()
        results.append({"scenario_id": "NEG-002", "issue_type": "INCOMPATIBLE_LOAD_ASSIGNMENT", "entity_ids": {"appointment": incompatible.id},
                        "expected": "REJECTED", "actual": incompatible.status, "expected_code": "DOCK_INCOMPATIBLE", "actual_code": decision.reason_code if decision else None,
                        "pass": incompatible_result is None and incompatible.status == "REJECTED"
                        and decision is not None and decision.reason_code == "DOCK_INCOMPATIBLE"})

        _, early = _case("NEG03")
        schedule_appointment(early)
        client = app.test_client(); client.post(f"/checkins/{early.id}")
        attempt = CheckInEvent.query.filter_by(appointment_id=early.id).first()
        results.append({"scenario_id": "NEG-003", "issue_type": "CHECK_IN_BEFORE_APPOINTMENT_DATE", "entity_ids": {"appointment": early.id},
                        "expected": "REJECTED_ATTEMPT", "actual": attempt.outcome if attempt else None, "expected_code": "EARLY_CHECK_IN", "actual_code": attempt.reason_code if attempt else None,
                        "pass": attempt is not None and attempt.outcome == "REJECTED"
                        and attempt.reason_code == "EARLY_CHECK_IN"
                        and early.status == "SCHEDULED"})

        _, labor = _case("NEG04", workers=0)
        labor_result = schedule_appointment(labor)
        decision = SchedulingDecision.query.filter_by(appointment_id=labor.id).order_by(SchedulingDecision.id.desc()).first()
        results.append({"scenario_id": "NEG-004", "issue_type": "LABOR_UNAVAILABLE", "entity_ids": {"appointment": labor.id},
                        "expected": "REJECTED", "actual": labor.status, "expected_code": "LABOR_UNAVAILABLE", "actual_code": decision.reason_code if decision else None,
                        "pass": labor_result is None and labor.status == "REJECTED"
                        and decision is not None and decision.reason_code == "LABOR_UNAVAILABLE"})

        old_start = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        _, no_show = _case("NEG05", start=old_start)
        schedule_appointment(no_show)
        missing = OperationalException.query.filter_by(appointment_id=no_show.id, cause_code="NO_SHOW").count() == 0
        results.append({"scenario_id": "NEG-005", "issue_type": "NO_SHOW_NOT_RECORDED", "entity_ids": {"appointment": no_show.id},
                        "expected": "MISSING_RECORD_DETECTED", "actual": "MISSING_RECORD_DETECTED" if missing else "RECORD_PRESENT", "expected_code": "NO_SHOW",
                        "actual_code": None if missing else "NO_SHOW", "pass": missing})
        return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--database-url", required=True); parser.add_argument("--output", default="scenario_results.json")
    args = parser.parse_args(); result = evaluate(args.database_url)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"scenarios": len(result), "passed": sum(row["pass"] for row in result), "output": args.output}))
