"""Date blocks and booking completion."""

import secrets
from datetime import date

from sqlalchemy import delete

from fipconnect.extensions import db
from fipconnect.models import Block, Booking
from fipconnect.models._types import as_decimal
from fipconnect.services.availability import is_unavailable, lock_date
from fipconnect.services.errors import reject
from fipconnect.services.inquiries import parse_date


def block_date(day, reason):
    blocked = parse_date(day)
    if not blocked or blocked < date.today():
        reject("Choose today or a future date to block.")
    lock_date(blocked)
    if is_unavailable(blocked):
        reject("That date is already unavailable.", 409, rollback=True)
    block = Block(
        id="block-" + secrets.token_urlsafe(10),
        date=blocked,
        reason=str(reason or "").strip()[:120],
    )
    db.session.add(block)
    db.session.commit()
    return block


def unblock(block_id):
    deleted = db.session.execute(delete(Block).where(Block.id == block_id)).rowcount
    db.session.commit()
    if not deleted:
        reject("Date block not found.", 404)


def complete_booking(booking_id, revenue):
    try:
        amount = float(revenue)
    except (TypeError, ValueError):
        reject("Actual revenue must be a valid number.")
    if not 0 <= amount <= 1_000_000_000:
        reject("Actual revenue must be a valid non-negative amount.")
    booking = db.session.get(Booking, booking_id)
    if booking is None:
        reject("Booking not found.", 404)
    if booking.status != "Confirmed":
        reject("Only confirmed bookings can be completed.", 409)
    booking.status = "Completed"
    booking.actual_revenue = as_decimal(amount)
    db.session.commit()
    return booking
