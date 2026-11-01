import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.domain import HandlingRequirement, YardSlot
from app.models.masters import Carrier, Facility, Vehicle
from app.models.operations import Shipment


@pytest.mark.parametrize(
    "entity",
    [
        lambda: Facility(code="NEG-F", name="Invalid", yard_capacity=-1),
        lambda: YardSlot(facility_id=1, code="NEG-Y", capacity=0),
        lambda: HandlingRequirement(shipment_id=1, required_workers=0),
        lambda: HandlingRequirement(shipment_id=1, service_minutes=0),
    ],
)
def test_schema_rejects_nonpositive_capacity_and_handling_values(app, entity):
    with app.app_context():
        db.session.add(entity())
        with pytest.raises(IntegrityError):
            db.session.flush()
        db.session.rollback()


def test_shipment_constraints_reject_invalid_direction_and_weight(app):
    with app.app_context():
        facility = Facility(code="CHECK-F", name="Check")
        carrier = Carrier(code="CHECK-C", name="Carrier")
        db.session.add_all([facility, carrier])
        db.session.flush()
        vehicle = Vehicle(
            carrier_id=carrier.id,
            registration="CHECK-V",
            vehicle_type="TRUCK",
        )
        db.session.add(vehicle)
        db.session.flush()

        invalid_direction = Shipment(
            reference="CHECK-S-DIRECTION",
            facility_id=facility.id,
            carrier_id=carrier.id,
            vehicle_id=vehicle.id,
            direction="SIDEWAYS",
            weight_kg=10,
        )
        db.session.add(invalid_direction)
        with pytest.raises(IntegrityError):
            db.session.flush()
        db.session.rollback()

        invalid_weight = Shipment(
            reference="CHECK-S-WEIGHT",
            facility_id=facility.id,
            carrier_id=carrier.id,
            vehicle_id=vehicle.id,
            direction="INBOUND",
            weight_kg=-1,
        )
        db.session.add(invalid_weight)
        with pytest.raises(IntegrityError):
            db.session.flush()
        db.session.rollback()
