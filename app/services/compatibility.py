def compatible(dock, appointment):
    shipment = appointment.shipment
    return dock.supports(shipment.direction, shipment.vehicle.vehicle_type)


def handling_yard_slot_type(requirement):
    if requirement and requirement.refrigerated and requirement.hazardous:
        return "REFRIGERATED_HAZARDOUS"
    if requirement and requirement.refrigerated:
        return "REFRIGERATED"
    if requirement and requirement.hazardous:
        return "HAZARDOUS"
    return "GENERAL"


def handles_requirement(resource_type, requirement):
    required = set()
    if requirement and requirement.refrigerated:
        required.add("REFRIGERATED")
    if requirement and requirement.hazardous:
        required.add("HAZARDOUS")
    if not required:
        return True

    value = resource_type.strip().upper()
    aliases = {
        frozenset({"REFRIGERATED", "HAZARDOUS"}): {
            "REFRIGERATED_HAZARDOUS",
            "COLD_HAZMAT",
        },
        frozenset({"REFRIGERATED"}): {"REFRIGERATED", "COLD"},
        frozenset({"HAZARDOUS"}): {"HAZARDOUS", "HAZMAT"},
    }
    return value in aliases[frozenset(required)]
