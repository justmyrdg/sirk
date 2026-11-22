from decimal import Decimal

STATUSES = (
    "Submitted",
    "Under Review",
    "Awaiting Client Response",
    "Approved",
    "Declined",
    "Cancelled",
)
PENDING_STATUSES = {"Submitted", "Under Review", "Awaiting Client Response"}
BOOKING_STATUSES = ("Confirmed", "Completed", "Cancelled")


def money(value):
    """Numeric columns come back as Decimal; the API has always sent numbers."""
    return None if value is None else float(value)


def as_decimal(value):
    return None if value is None else Decimal(str(value)).quantize(Decimal("0.01"))


def in_list(column, values):
    """SQL for a CHECK constraint limiting a column to fixed values."""
    quoted = ", ".join("'{}'".format(value) for value in values)
    return f"{column} IN ({quoted})"
