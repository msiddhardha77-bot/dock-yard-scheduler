def appointment_payload(reference, shipment_id, facility_id, requested_start, requested_end, duration_minutes=60):
    return {"reference": reference, "shipment_id": shipment_id, "facility_id": facility_id,
            "requested_start": requested_start, "requested_end": requested_end, "duration_minutes": duration_minutes}

