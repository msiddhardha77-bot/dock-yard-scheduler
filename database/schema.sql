-- DockFlow standalone schema export.
-- Target dialect: SQLite 3 (the local/test database dialect).
-- Generated from the SQLAlchemy metadata in app/models/*.py.
-- This file contains schema only: no sample data, credentials, or database
-- contents. Python-side defaults and lifecycle/business rules remain in the
-- application services; only database constraints are represented here.

PRAGMA foreign_keys = ON;

CREATE TABLE anomaly_labels (
    id INTEGER NOT NULL,
    appointment_id INTEGER NOT NULL,
    label VARCHAR(50) NOT NULL,
    source VARCHAR(30) NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (appointment_id) REFERENCES appointments (id)
);

CREATE TABLE appointment_timelines (
    id INTEGER NOT NULL,
    appointment_id INTEGER NOT NULL,
    actual_arrival_at DATETIME,
    yard_entry_at DATETIME,
    dock_arrival_at DATETIME,
    service_start_at DATETIME,
    service_end_at DATETIME,
    departure_at DATETIME,
    PRIMARY KEY (id),
    UNIQUE (appointment_id),
    FOREIGN KEY (appointment_id) REFERENCES appointments (id)
);

CREATE TABLE appointments (
    id INTEGER NOT NULL,
    reference VARCHAR(50) NOT NULL,
    shipment_id INTEGER NOT NULL,
    facility_id INTEGER NOT NULL,
    requested_start DATETIME NOT NULL,
    requested_end DATETIME NOT NULL,
    scheduled_start DATETIME,
    scheduled_end DATETIME,
    duration_minutes INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_appointment_requested_window CHECK (requested_end > requested_start),
    CONSTRAINT ck_appointment_duration_positive CHECK (duration_minutes > 0),
    CONSTRAINT ck_appointment_status CHECK (status IN (
        'REQUESTED', 'SCHEDULED', 'CHECKED_IN', 'AT_DOCK', 'IN_SERVICE',
        'COMPLETED', 'DEPARTED', 'CANCELLED', 'REJECTED', 'NO_SHOW'
    )),
    UNIQUE (reference),
    FOREIGN KEY (shipment_id) REFERENCES shipments (id),
    FOREIGN KEY (facility_id) REFERENCES facilities (id)
);

CREATE TABLE carriers (
    id INTEGER NOT NULL,
    code VARCHAR(30) NOT NULL,
    name VARCHAR(120) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (code)
);

CREATE TABLE check_in_events (
    id INTEGER NOT NULL,
    event_reference VARCHAR(60) NOT NULL,
    appointment_id INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL,
    attempted_at DATETIME NOT NULL,
    outcome VARCHAR(30) NOT NULL,
    reason_code VARCHAR(60),
    PRIMARY KEY (id),
    CONSTRAINT uq_checkin_attempt UNIQUE (appointment_id, attempt_number),
    CONSTRAINT ck_checkin_attempt_number CHECK (attempt_number > 0),
    CONSTRAINT ck_checkin_outcome CHECK (outcome IN ('ACCEPTED', 'REJECTED')),
    UNIQUE (event_reference),
    FOREIGN KEY (appointment_id) REFERENCES appointments (id)
);

CREATE TABLE dock_reservations (
    id INTEGER NOT NULL,
    dock_id INTEGER NOT NULL,
    appointment_id INTEGER NOT NULL,
    start_at DATETIME NOT NULL,
    end_at DATETIME NOT NULL,
    status VARCHAR(20) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_reservation_time_order CHECK (end_at > start_at),
    CONSTRAINT ck_dock_reservation_status CHECK (status IN ('ACTIVE', 'CANCELLED', 'COMPLETED')),
    FOREIGN KEY (dock_id) REFERENCES docks (id),
    FOREIGN KEY (appointment_id) REFERENCES appointments (id)
);

CREATE TABLE docks (
    id INTEGER NOT NULL,
    facility_id INTEGER NOT NULL,
    code VARCHAR(30) NOT NULL,
    dock_type VARCHAR(30) NOT NULL,
    supports_inbound BOOLEAN NOT NULL,
    supports_outbound BOOLEAN NOT NULL,
    vehicle_types VARCHAR(255) NOT NULL,
    active BOOLEAN NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_dock_facility_code UNIQUE (facility_id, code),
    FOREIGN KEY (facility_id) REFERENCES facilities (id)
);

CREATE TABLE drivers (
    id INTEGER NOT NULL,
    carrier_id INTEGER NOT NULL,
    name VARCHAR(120) NOT NULL,
    license_number VARCHAR(50) NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (carrier_id) REFERENCES carriers (id),
    UNIQUE (license_number)
);

CREATE TABLE facilities (
    id INTEGER NOT NULL,
    code VARCHAR(20) NOT NULL,
    name VARCHAR(120) NOT NULL,
    timezone VARCHAR(64) NOT NULL,
    operating_start TIME NOT NULL,
    operating_end TIME NOT NULL,
    yard_capacity INTEGER NOT NULL,
    active BOOLEAN NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_facility_yard_capacity CHECK (yard_capacity >= 0),
    UNIQUE (code)
);

CREATE TABLE gate_visits (
    id INTEGER NOT NULL,
    appointment_id INTEGER NOT NULL,
    check_in_at DATETIME NOT NULL,
    check_out_at DATETIME,
    PRIMARY KEY (id),
    UNIQUE (appointment_id),
    FOREIGN KEY (appointment_id) REFERENCES appointments (id)
);

CREATE TABLE ground_truth_records (
    id INTEGER NOT NULL,
    entity_type VARCHAR(40) NOT NULL,
    entity_id INTEGER NOT NULL,
    truth JSON NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE handling_requirements (
    id INTEGER NOT NULL,
    shipment_id INTEGER NOT NULL,
    refrigerated BOOLEAN NOT NULL,
    hazardous BOOLEAN NOT NULL,
    required_workers INTEGER NOT NULL,
    service_minutes INTEGER NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_handling_required_workers CHECK (required_workers > 0),
    CONSTRAINT ck_handling_service_minutes CHECK (service_minutes > 0),
    FOREIGN KEY (shipment_id) REFERENCES shipments (id)
);

CREATE TABLE labor_assignments (
    id INTEGER NOT NULL,
    shift_id INTEGER NOT NULL,
    appointment_id INTEGER NOT NULL,
    workers INTEGER NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_labor_assignment_appointment UNIQUE (appointment_id),
    CONSTRAINT ck_labor_assignment_workers CHECK (workers > 0),
    FOREIGN KEY (shift_id) REFERENCES labor_shifts (id),
    FOREIGN KEY (appointment_id) REFERENCES appointments (id)
);

CREATE TABLE labor_shifts (
    id INTEGER NOT NULL,
    facility_id INTEGER NOT NULL,
    name VARCHAR(50) NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    workers INTEGER NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_labor_shift_workers CHECK (workers >= 0),
    FOREIGN KEY (facility_id) REFERENCES facilities (id)
);

CREATE TABLE lifecycle_events (
    id INTEGER NOT NULL,
    appointment_id INTEGER NOT NULL,
    from_status VARCHAR(20),
    to_status VARCHAR(20) NOT NULL,
    event_type VARCHAR(40) NOT NULL,
    event_time DATETIME NOT NULL,
    notes TEXT,
    PRIMARY KEY (id),
    FOREIGN KEY (appointment_id) REFERENCES appointments (id)
);

CREATE TABLE operational_exceptions (
    id INTEGER NOT NULL,
    appointment_id INTEGER,
    facility_id INTEGER NOT NULL,
    severity VARCHAR(20) NOT NULL,
    cause_code VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    detected_at DATETIME NOT NULL,
    resolved_at DATETIME,
    resolution_notes TEXT,
    status VARCHAR(20) NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (appointment_id) REFERENCES appointments (id),
    FOREIGN KEY (facility_id) REFERENCES facilities (id)
);

CREATE TABLE scheduling_decisions (
    id INTEGER NOT NULL,
    appointment_id INTEGER NOT NULL,
    decision VARCHAR(20) NOT NULL,
    reason_code VARCHAR(60) NOT NULL,
    details JSON NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (appointment_id) REFERENCES appointments (id)
);

CREATE TABLE shipments (
    id INTEGER NOT NULL,
    reference VARCHAR(50) NOT NULL,
    facility_id INTEGER NOT NULL,
    carrier_id INTEGER NOT NULL,
    vehicle_id INTEGER NOT NULL,
    direction VARCHAR(10) NOT NULL,
    weight_kg INTEGER NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_shipment_direction CHECK (direction IN ('INBOUND', 'OUTBOUND')),
    CONSTRAINT ck_shipment_weight_nonnegative CHECK (weight_kg >= 0),
    UNIQUE (reference),
    FOREIGN KEY (facility_id) REFERENCES facilities (id),
    FOREIGN KEY (carrier_id) REFERENCES carriers (id),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles (id)
);

CREATE TABLE simulation_runs (
    id INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    mode VARCHAR(20) NOT NULL,
    started_at DATETIME NOT NULL,
    completed_at DATETIME,
    manifest JSON,
    PRIMARY KEY (id)
);

CREATE TABLE vehicles (
    id INTEGER NOT NULL,
    carrier_id INTEGER NOT NULL,
    registration VARCHAR(30) NOT NULL,
    vehicle_type VARCHAR(30) NOT NULL,
    capacity_kg INTEGER NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (carrier_id) REFERENCES carriers (id),
    UNIQUE (registration)
);

CREATE TABLE yard_occupancy (
    id INTEGER NOT NULL,
    facility_id INTEGER NOT NULL,
    appointment_id INTEGER NOT NULL,
    entered_at DATETIME NOT NULL,
    exited_at DATETIME,
    PRIMARY KEY (id),
    CONSTRAINT ck_yard_occupancy_time_order CHECK (exited_at IS NULL OR exited_at >= entered_at),
    FOREIGN KEY (facility_id) REFERENCES facilities (id),
    FOREIGN KEY (appointment_id) REFERENCES appointments (id)
);

CREATE TABLE yard_slot_reservations (
    id INTEGER NOT NULL,
    yard_slot_id INTEGER NOT NULL,
    appointment_id INTEGER NOT NULL,
    start_at DATETIME NOT NULL,
    end_at DATETIME NOT NULL,
    status VARCHAR(20) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_yard_slot_reservation_time CHECK (end_at > start_at),
    CONSTRAINT ck_yard_slot_reservation_status CHECK (status IN ('ACTIVE', 'CANCELLED', 'COMPLETED')),
    FOREIGN KEY (yard_slot_id) REFERENCES yard_slots (id),
    FOREIGN KEY (appointment_id) REFERENCES appointments (id)
);

CREATE TABLE yard_slots (
    id INTEGER NOT NULL,
    facility_id INTEGER NOT NULL,
    code VARCHAR(40) NOT NULL,
    capacity INTEGER NOT NULL,
    slot_type VARCHAR(30) NOT NULL,
    active BOOLEAN NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_yard_slot_facility_code UNIQUE (facility_id, code),
    CONSTRAINT ck_yard_slot_capacity CHECK (capacity > 0),
    FOREIGN KEY (facility_id) REFERENCES facilities (id)
);

CREATE TABLE yard_zones (
    id INTEGER NOT NULL,
    facility_id INTEGER NOT NULL,
    code VARCHAR(30) NOT NULL,
    capacity INTEGER NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_zone_facility_code UNIQUE (facility_id, code),
    FOREIGN KEY (facility_id) REFERENCES facilities (id)
);

CREATE INDEX ix_appointments_facility_id ON appointments (facility_id);
CREATE INDEX ix_appointments_requested_start ON appointments (requested_start);
CREATE INDEX ix_appointments_shipment_id ON appointments (shipment_id);
CREATE INDEX ix_appointments_status ON appointments (status);
CREATE INDEX ix_check_in_events_appointment_id ON check_in_events (appointment_id);
CREATE INDEX ix_dock_reservations_appointment_id ON dock_reservations (appointment_id);
CREATE INDEX ix_dock_reservations_dock_id ON dock_reservations (dock_id);
CREATE INDEX ix_dock_reservations_start_at ON dock_reservations (start_at);
CREATE INDEX ix_dock_reservations_status ON dock_reservations (status);
CREATE INDEX ix_docks_facility_id ON docks (facility_id);
CREATE UNIQUE INDEX ix_handling_requirements_shipment_id ON handling_requirements (shipment_id);
CREATE INDEX ix_labor_assignments_appointment_id ON labor_assignments (appointment_id);
CREATE INDEX ix_labor_assignments_shift_id ON labor_assignments (shift_id);
CREATE INDEX ix_lifecycle_events_appointment_id ON lifecycle_events (appointment_id);
CREATE INDEX ix_lifecycle_events_event_time ON lifecycle_events (event_time);
CREATE INDEX ix_operational_exceptions_appointment_id ON operational_exceptions (appointment_id);
CREATE INDEX ix_operational_exceptions_facility_id ON operational_exceptions (facility_id);
CREATE INDEX ix_operational_exceptions_status ON operational_exceptions (status);
CREATE INDEX ix_scheduling_decisions_appointment_id ON scheduling_decisions (appointment_id);
CREATE INDEX ix_yard_occupancy_facility_id ON yard_occupancy (facility_id);
CREATE INDEX ix_yard_slot_reservations_appointment_id ON yard_slot_reservations (appointment_id);
CREATE INDEX ix_yard_slot_reservations_yard_slot_id ON yard_slot_reservations (yard_slot_id);
CREATE INDEX ix_yard_slots_facility_id ON yard_slots (facility_id);
