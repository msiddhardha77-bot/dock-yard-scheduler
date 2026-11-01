import argparse
import logging
import os
import random
import re
import time as clock
from datetime import datetime, timedelta, timezone, time
from pathlib import Path
from app import create_app, db
from app.models.masters import (
    Facility,
    Dock,
    Carrier,
    Vehicle,
    LaborShift,
)
from app.models.operations import Shipment, Appointment
from app.models.events import LifecycleEvent, AnomalyLabel, GroundTruthRecord
from app.models.scheduling import SchedulingDecision
from app.models.domain import (
    YardSlot,
    HandlingRequirement,
    AppointmentTimeline,
)
from app.models.events import OperationalException, SimulationRun
from app.services.scheduler import schedule_appointment
from config import Config
from generator.settings import (
    STARTER,
    MEDIUM,
    FULL,
    MASTER_DATA,
    FACILITY_APPOINTMENT_WEIGHTS,
)
from generator.anomalies import appointment_arrival_label, inject_anomalies

logger = logging.getLogger(__name__)
LOG_FILE = Path(__file__).resolve().parents[1] / "logs" / "full_generation.log"


class CredentialRedactingFormatter(logging.Formatter):
    credential_url = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@")

    def format(self, record):
        return self.credential_url.sub(r"\1<redacted>@", super().format(record))


def configure_generation_logging(log_file=LOG_FILE):
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = CredentialRedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handlers = [
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(),
    ]
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)


def _start_stage(progress, stage):
    now = clock.perf_counter()
    if progress["stage"] is not None:
        logger.info(
            "stage_completed stage=%s elapsed_seconds=%.2f",
            progress["stage"], now - progress["stage_started"],
        )
    progress["stage"] = stage
    progress["stage_started"] = now
    logger.info("stage_started stage=%s elapsed_total_seconds=%.2f", stage, now - progress["started"])


def _allocate_facility_appointments(total, weights):
    if total < 0 or not weights or any(weight <= 0 for weight in weights):
        raise ValueError(
            "Appointment count must be nonnegative and weights must be positive"
        )
    total_weight = sum(weights)
    expected_counts = [total * weight / total_weight for weight in weights]
    allocated_counts = [int(expected_count) for expected_count in expected_counts]
    remaining = total - sum(allocated_counts)
    remainder_order = sorted(
        range(len(weights)),
        key=lambda index: (
            expected_counts[index] - allocated_counts[index],
            -index,
        ),
        reverse=True,
    )
    for index in remainder_order[:remaining]:
        allocated_counts[index] += 1
    return allocated_counts


def _generate(seed, mode, progress, database_url=None):
    _start_stage(progress, "app_initialization")
    try:
        config = {"starter": STARTER, "medium": MEDIUM, "full": FULL}[mode]
    except KeyError as exc:
        raise ValueError(f"Unsupported generation mode: {mode}") from exc
    expected_docks = (
        config["facilities"]
        * sum(MASTER_DATA["docks_per_facility"].values())
    )
    if config["docks"] != expected_docks:
        raise ValueError(
            f"Mode {mode} config requests {config['docks']} docks, "
            f"but the resource profile creates {expected_docks}"
        )
    rng = random.Random(seed)
    if database_url:
        generation_config = type(
            "GenerationConfig",
            (Config,),
            {"SQLALCHEMY_DATABASE_URI": database_url},
        )
        app = create_app(generation_config)
    else:
        app = create_app()
    with app.app_context():
        _start_stage(progress, "schema_initialization_and_idempotency_check")
        db.create_all()
        existing_run = SimulationRun.query.filter_by(seed=seed, mode=mode).first()
        if existing_run:
            existing = Appointment.query.filter(Appointment.reference.like("APPT-2026-%")).count()
            logger.info("generation_reused seed=%s mode=%s appointments=%s", seed, mode, existing)
            return {"mode": mode, "seed": seed, "facilities": Facility.query.filter(Facility.code.like("FAC-%")).count(), "appointments": existing, "reused": True}
        _start_stage(progress, "master_data_creation")
        prefix = f"S{seed}{mode[0].upper()}"
        for i in range(config["facilities"]):
            facility = Facility(code=f"FAC-{i+1:03d}", name=f"Synthetic Facility {i+1}", yard_capacity=50)
            db.session.add(facility); db.session.flush()
            db.session.add_all(
                [
                    LaborShift(
                        facility_id=facility.id,
                        name="Day",
                        start_time=time(6),
                        end_time=time(15),
                        workers=12,
                    ),
                    LaborShift(
                        facility_id=facility.id,
                        name="Evening",
                        start_time=time(13),
                        end_time=time(22),
                        workers=12,
                    ),
                ]
            )
            dock_number = 0
            for dock_type, count in MASTER_DATA["docks_per_facility"].items():
                for _ in range(count):
                    dock_number += 1
                    db.session.add(
                        Dock(
                            facility_id=facility.id,
                            code=f"DOCK-{facility.code}-{dock_number:03d}",
                            dock_type=dock_type,
                            vehicle_types="VAN,TRUCK,TRAILER",
                        )
                    )
            slot_number = 0
            for slot_type, count in MASTER_DATA[
                "yard_slots_per_facility"
            ].items():
                for _ in range(count):
                    slot_number += 1
                    db.session.add(
                        YardSlot(
                            facility_id=facility.id,
                            code=f"YARD-{facility.code}-{slot_number:03d}",
                            capacity=5,
                            slot_type=slot_type,
                        )
                    )
        db.session.flush()

        carriers = []
        vehicles_by_carrier = {}
        vehicle_types = MASTER_DATA["vehicle_types"]
        for carrier_index in range(1, MASTER_DATA["carriers"] + 1):
            carrier = Carrier(
                code=f"{prefix}-CAR-{carrier_index:03d}",
                name=f"Synthetic Carrier {carrier_index:03d}",
            )
            db.session.add(carrier)
            db.session.flush()
            carriers.append(carrier)
            vehicles = {}
            for vehicle_type, profile in vehicle_types.items():
                vehicle = Vehicle(
                    carrier_id=carrier.id,
                    registration=(
                        f"{prefix}-VEH-{carrier_index:03d}-{vehicle_type}"
                    ),
                    vehicle_type=vehicle_type,
                    capacity_kg=profile["capacity_kg"],
                )
                db.session.add(vehicle)
                vehicles[vehicle_type] = vehicle
            vehicles_by_carrier[carrier.id] = vehicles
        db.session.flush()

        # Fixed synthetic clock makes repeated runs with the same seed reproducible.
        start = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc) + timedelta(days=seed % 365)
        facilities = Facility.query.filter(Facility.code.like("FAC-%")).order_by(Facility.code).all()
        if len(facilities) != config["facilities"]:
            raise RuntimeError(
                f"Expected {config['facilities']} generated facilities, "
                f"found {len(facilities)}"
            )
        facility_weights = FACILITY_APPOINTMENT_WEIGHTS[: len(facilities)]
        if len(facility_weights) != len(facilities):
            raise RuntimeError(
                "No appointment distribution weights for generated facilities"
            )
        allocated_facility_counts = _allocate_facility_appointments(
            config["appointments"],
            facility_weights,
        )
        max_daily_slots = (
            MASTER_DATA["appointments_per_day_per_facility"] * 60
        )
        if max(allocated_facility_counts) > max_daily_slots:
            raise RuntimeError(
                "Configured facility allocation exceeds the 60-day horizon"
            )
        facility_schedule = [
            facility
            for facility, appointment_count in zip(
                facilities,
                allocated_facility_counts,
            )
            for _ in range(appointment_count)
        ]
        rng.shuffle(facility_schedule)
        facility_appointment_numbers = {facility.id: 0 for facility in facilities}
        carrier_by_id = {carrier.id: carrier for carrier in carriers}
        carrier_appointment_counts = {carrier.id: 0 for carrier in carriers}
        vehicle_type_counts = {vehicle_type: 0 for vehicle_type in vehicle_types}
        refrigerated_count = 0
        hazardous_count = 0
        _start_stage(progress, "appointment_creation_and_scheduling")
        scheduled_count = 0
        rejected_count = 0
        for i in range(config["appointments"]):
            facility = facility_schedule[i]
            facility_sequence = facility_appointment_numbers[facility.id]
            facility_appointment_numbers[facility.id] += 1
            day, daily_slot = divmod(
                facility_sequence,
                MASTER_DATA["appointments_per_day_per_facility"],
            )
            if day >= 60:
                raise RuntimeError(
                    f"Appointment allocation exceeds 60-day horizon at "
                    f"{facility.code}"
                )
            requested = start + timedelta(
                days=day,
                minutes=(
                    daily_slot * MASTER_DATA["appointment_interval_minutes"]
                ),
            )

            carrier = rng.choice(carriers)
            carrier_appointment_counts[carrier.id] += 1
            vehicle_type = rng.choices(
                list(vehicle_types),
                weights=[
                    profile["weight"] for profile in vehicle_types.values()
                ],
                k=1,
            )[0]
            vehicle = vehicles_by_carrier[carrier.id][vehicle_type]
            vehicle_type_counts[vehicle_type] += 1
            weight_kg = rng.randint(1000, vehicle.capacity_kg)
            shipment = Shipment(reference=f"SHP-2026-{i+1:06d}", facility_id=facility.id, carrier_id=carrier.id, vehicle_id=vehicle.id,
                                direction="INBOUND" if i % 2 == 0 else "OUTBOUND", weight_kg=weight_kg)
            db.session.add(shipment); db.session.flush()
            refrigerated = i % 10 == 0
            hazardous = i % 20 == 5
            refrigerated_count += refrigerated
            hazardous_count += hazardous
            requirement = HandlingRequirement(shipment_id=shipment.id, refrigerated=refrigerated, hazardous=hazardous,
                                              required_workers=2 if (refrigerated or hazardous) else 1,
                                              service_minutes=90 if (refrigerated or hazardous) else 60)
            db.session.add(requirement); db.session.flush()
            appointment = Appointment(reference=f"APPT-2026-{i+1:06d}", shipment_id=shipment.id, facility_id=facility.id,
                                      requested_start=requested, requested_end=requested + timedelta(hours=2), duration_minutes=requirement.service_minutes,
                                      created_at=requested - timedelta(days=1))
            db.session.add(appointment); db.session.flush(); schedule_appointment(appointment, commit=False, decision_time=appointment.created_at, record_lifecycle=False)
            actual_arrival = requested - timedelta(minutes=10)
            if appointment.status == "SCHEDULED":
                db.session.add(AppointmentTimeline(appointment_id=appointment.id, actual_arrival_at=actual_arrival,
                                                   yard_entry_at=requested - timedelta(minutes=8), dock_arrival_at=requested - timedelta(minutes=2),
                                                   service_start_at=requested, service_end_at=requested + timedelta(minutes=appointment.duration_minutes),
                                                   departure_at=requested + timedelta(minutes=appointment.duration_minutes + 5)))
            else:
                db.session.add(AppointmentTimeline(appointment_id=appointment.id))
            label = appointment_arrival_label(actual_arrival, requested)
            db.session.add(AnomalyLabel(appointment_id=appointment.id, label=label))
            db.session.add(GroundTruthRecord(
                entity_type="appointment",
                entity_id=appointment.id,
                truth={"issue_type": label, "label": label, "seed": seed},
            ))
            scheduled_count += appointment.status == "SCHEDULED"
            rejected_count += appointment.status != "SCHEDULED"
            if (i + 1) % 500 == 0:
                db.session.commit()
                logger.info(
                    "generation_progress stage=appointment_creation_and_scheduling completed=%s target=%s scheduled=%s rejected=%s elapsed_seconds=%.2f",
                    i + 1, config["appointments"], scheduled_count, rejected_count,
                    clock.perf_counter() - progress["started"],
                )
        db.session.commit()
        _start_stage(progress, "labelled_anomaly_injection")
        anomaly_types = inject_anomalies(start + timedelta(days=60))
        db.session.commit()
        _start_stage(progress, "lifecycle_event_preparation")
        if mode == "full":
            appointments = Appointment.query.filter(Appointment.reference.like("APPT-2026-%")).all()
            event_rows = []
            for event_index, appointment in enumerate(appointments, 1):
                final_status = appointment.status
                if final_status == "SCHEDULED":
                    states = [(None, "REQUESTED"), ("REQUESTED", "SCHEDULED"), ("SCHEDULED", "SCHEDULED"), ("SCHEDULED", "SCHEDULED"), ("SCHEDULED", "SCHEDULED")]
                    event_names = ["REQUESTED", "SCHEDULE_ATTEMPT", "DOCK_ALLOCATION", "LABOR_CHECK", "YARD_CHECK"]
                else:
                    # Rejections have a terminal REQUESTED -> REJECTED history; the
                    # remaining rows are same-state operational audit markers.
                    states = [(None, "REQUESTED"), ("REQUESTED", "REJECTED"), ("REJECTED", "REJECTED"), ("REJECTED", "REJECTED"), ("REJECTED", "REJECTED")]
                    event_names = ["REQUESTED", "SCHEDULE_ATTEMPT", "REJECTION_RECORDED", "CAPACITY_CHECK", "AUDIT_MARKER"]
                for offset, ((from_status, to_status), event_name) in enumerate(zip(states, event_names)):
                    event_rows.append(LifecycleEvent(appointment_id=appointment.id, from_status=from_status, to_status=to_status,
                                                     event_type=event_name, event_time=appointment.created_at + timedelta(minutes=offset)))
                if event_index % 1000 == 0:
                    logger.info("generation_progress stage=lifecycle_event_preparation appointments=%s target=%s event_rows=%s elapsed_seconds=%.2f", event_index, len(appointments), len(event_rows), clock.perf_counter() - progress["started"])
        else:
            appointments = Appointment.query.filter(Appointment.reference.like("APPT-2026-%")).all()
            event_rows = []
            for appointment in appointments:
                event_rows.append(LifecycleEvent(appointment_id=appointment.id, from_status=None, to_status="REQUESTED",
                                                 event_type="REQUESTED", event_time=appointment.created_at))
                event_rows.append(LifecycleEvent(appointment_id=appointment.id, from_status="REQUESTED", to_status=appointment.status,
                                                 event_type="SCHEDULE_RESULT", event_time=appointment.created_at + timedelta(minutes=1)))
                if len(event_rows) % 1000 == 0:
                    logger.info("generation_progress stage=lifecycle_event_preparation event_rows=%s elapsed_seconds=%.2f", len(event_rows), clock.perf_counter() - progress["started"])
        logger.info("stage_progress stage=lifecycle_event_preparation appointments=%s event_rows=%s", len(appointments), len(event_rows))
        _start_stage(progress, "lifecycle_event_bulk_insert_and_commit")
        db.session.bulk_save_objects(event_rows); db.session.commit()
        logger.info("lifecycle_events_persisted count=%s elapsed_seconds=%.2f", len(event_rows), clock.perf_counter() - progress["started"])
        _start_stage(progress, "simulation_run_manifest_commit")
        count = Appointment.query.filter(Appointment.reference.like("APPT-2026-%")).count()
        run = SimulationRun(seed=seed, mode=mode, started_at=start - timedelta(days=1), completed_at=start + timedelta(days=60),
                            manifest={"horizon_days": 60, "yard_slots_per_facility": 10, "handling_requirement_per_shipment": True})
        db.session.add(run); db.session.commit()
        _start_stage(progress, "result_summary")
        appointment_ids = db.session.query(Appointment.id).filter(
            Appointment.reference.like("APPT-2026-%")
        ).subquery()
        anomaly_distribution = dict(
            db.session.query(AnomalyLabel.label, db.func.count(AnomalyLabel.id))
            .join(appointment_ids, appointment_ids.c.id == AnomalyLabel.appointment_id)
            .group_by(AnomalyLabel.label)
            .order_by(AnomalyLabel.label)
            .all()
        )
        exception_distribution = dict(
            db.session.query(
                OperationalException.cause_code,
                db.func.count(OperationalException.id),
            )
            .group_by(OperationalException.cause_code)
            .order_by(OperationalException.cause_code)
            .all()
        )
        rejection_reason_distribution = dict(
            db.session.query(
                SchedulingDecision.reason_code,
                db.func.count(SchedulingDecision.id),
            )
            .join(
                appointment_ids,
                appointment_ids.c.id == SchedulingDecision.appointment_id,
            )
            .filter(SchedulingDecision.decision == "REJECTED")
            .group_by(SchedulingDecision.reason_code)
            .order_by(SchedulingDecision.reason_code)
            .all()
        )
        return {"mode": mode, "seed": seed, "facilities": len(facilities), "docks": sum(len(f.docks) for f in facilities), "yard_slots": YardSlot.query.count(), "handling_requirements": HandlingRequirement.query.count(), "appointments": count,
                "events": LifecycleEvent.query.filter(LifecycleEvent.appointment_id.in_([a.id for a in Appointment.query.filter(Appointment.reference.like("APPT-2026-%")).all()])).count(),
                "carriers": len(carriers),
                "vehicles": sum(len(vehicles) for vehicles in vehicles_by_carrier.values()),
                "labor_shifts": LaborShift.query.filter(
                    LaborShift.facility_id.in_([facility.id for facility in facilities])
                ).count(),
                "scheduled_appointments": scheduled_count,
                "rejected_appointments": rejected_count,
                "facility_appointment_distribution": {
                    facility.code: facility_appointment_numbers[facility.id]
                    for facility in facilities
                },
                "carrier_appointment_distribution": {
                    carrier_by_id[carrier_id].code: count
                    for carrier_id, count in sorted(
                        carrier_appointment_counts.items(),
                        key=lambda item: carrier_by_id[item[0]].code,
                    )
                },
                "vehicle_type_distribution": vehicle_type_counts,
                "refrigerated_shipments": refrigerated_count,
                "hazardous_shipments": hazardous_count,
                "anomalies": anomaly_types,
                "anomaly_distribution": anomaly_distribution,
                "exception_distribution": exception_distribution,
                "rejection_reason_distribution": rejection_reason_distribution}


def generate(seed=20261022, mode="starter", database_url=None):
    started = clock.perf_counter()
    progress = {"started": started, "stage": None, "stage_started": started}
    logger.info("generation_started seed=%s mode=%s", seed, mode)
    try:
        result = _generate(seed, mode, progress, database_url)
    except Exception:
        logger.exception(
            "generation_failed stage=%s stage_elapsed_seconds=%.2f elapsed_total_seconds=%.2f",
            progress["stage"], clock.perf_counter() - progress["stage_started"],
            clock.perf_counter() - started,
        )
        raise
    now = clock.perf_counter()
    if progress["stage"] is not None:
        logger.info("stage_completed stage=%s elapsed_seconds=%.2f", progress["stage"], now - progress["stage_started"])
    logger.info("generation_completed elapsed_seconds=%.2f result=%s", now - started, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--mode", choices=["starter", "medium", "full"], default="starter"); parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--log-file", default=str(LOG_FILE))
    parser.add_argument("--database-url")
    args = parser.parse_args()
    configure_generation_logging(args.log_file)
    log_path = Path(args.log_file)
    log_path.with_name("full_generation.pid").write_text(str(os.getpid()), encoding="utf-8")
    exit_code = 1
    try:
        print(generate(args.seed, args.mode, args.database_url))
        exit_code = 0
    finally:
        log_path.with_name("full_generation.exitcode").write_text(str(exit_code), encoding="utf-8")
