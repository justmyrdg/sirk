"""Which dates are taken, and locks so two requests can't claim one date."""

from sqlalchemy import select, text

from fipconnect.extensions import db
from fipconnect.models import Block, Booking

# Advisory lock keys live in their own number range so they can't collide
# with locks other code might take on the same database.
_DATE_LOCK_BASE = 7_000_000_000
_SETUP_LOCK_KEY = 7_000_000_001


def unavailable_dates():
    """ISO dates of confirmed bookings and blocked days."""
    booked = db.session.scalars(
        select(Booking.date).where(Booking.status == "Confirmed")
    )
    blocked = db.session.scalars(select(Block.date))
    return {value.isoformat() for value in [*booked, *blocked]}


def is_unavailable(day):
    booked = db.session.scalar(
        select(Booking.id).where(Booking.date == day, Booking.status == "Confirmed").limit(1)
    )
    if booked:
        return True
    return db.session.scalar(select(Block.id).where(Block.date == day).limit(1)) is not None


def _advisory_lock(key):
    db.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def lock_date(day):
    """Hold a lock on this date until the current transaction ends."""
    _advisory_lock(_DATE_LOCK_BASE + int(day.strftime("%Y%m%d")))


def lock_setup():
    """Hold the first-admin setup lock until the current transaction ends."""
    _advisory_lock(_SETUP_LOCK_KEY)
