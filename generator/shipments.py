def shipment_payload(reference, facility_id, carrier_id, vehicle_id, direction, weight_kg):
    return {"reference": reference, "facility_id": facility_id, "carrier_id": carrier_id,
            "vehicle_id": vehicle_id, "direction": direction, "weight_kg": weight_kg}

