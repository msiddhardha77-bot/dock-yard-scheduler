from datetime import timedelta


def slots(start, count, minutes=30):
    return [start + timedelta(minutes=minutes * n) for n in range(count)]

