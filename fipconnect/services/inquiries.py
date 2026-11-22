"""Client inquiries: submitting, looking up, and changing status."""

import math
import re
import secrets
from datetime import date, timedelta

from flask import current_app

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from fipconnect.extensions import db
from fipconnect.models import STATUSES, Booking, Inquiry
from fipconnect.models._types import as_decimal
from fipconnect.services.availability import is_unavailable, lock_date
from fipconnect.services.errors import reject
from fipconnect.services.metrics import local_today
from fipconnect.services.notifications import notify_client

REFERENCE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
REFERENCE_ATTEMPTS = 5


def new_reference():
    return "FIP-" + "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(8))


def earliest_bookable(today=None):
    """First date a client may request: today (Philippine date) plus the
    minimum lead time (FIP_MIN_LEAD_DAYS, default 7). Admins aren't limited."""
    return (today or local_today()) + timedelta(days=current_app.config["MIN_LEAD_DAYS"])


def parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _clean(data):
    """Validate a submitted inquiry; returns model fields or raises."""
    required = ("name", "email", "phone", "eventName", "eventDate")
    if any(not isinstance(data.get(field), str) or not data[field].strip() for field in required):
        reject("Please provide your name, email, contact number, event type, and date.")
    name = data["name"].strip()
    email = data["email"].strip()
    phone = data["phone"].strip()
    event_name = data["eventName"].strip()
    event_date = parse_date(data["eventDate"].strip())
    if len(name) > 120 or len(email) > 160 or len(phone) > 40 or len(event_name) > 120:
        reject("One or more inquiry fields exceed the allowed length.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        reject("Please enter a valid email address.")
    today = local_today()
    if not event_date or event_date < today:
        reject("Please choose today or a future event date.")
    if event_date < earliest_bookable(today):
        lead = current_app.config["MIN_LEAD_DAYS"]
        reject(f"Please choose a date at least {lead} day{'s' if lead != 1 else ''} from today.")
    if len(str(data.get("venue") or "")) > 180 or len(str(data.get("notes") or "")) > 2000:
        reject("Venue or additional requirements exceed the allowed length.")
    guests = data.get("guests")
    budget = data.get("budget")
    try:
        guests = int(guests) if guests not in (None, "") else None
        budget = float(budget) if budget not in (None, "") else None
    except (TypeError, ValueError):
        reject("Guest count and budget must be valid numbers.")
    if guests is not None and not 1 <= guests <= 100000:
        reject("Guest count must be between 1 and 100000.")
    if budget is not None and (not math.isfinite(budget) or budget < 0 or budget > 1_000_000_000):
        reject("Budget must be a non-negative valid amount.")
    return {
        "name": name,
        "email": email,
        "phone": phone,
        "event_name": event_name,
        "event_date": event_date,
        "venue": str(data.get("venue") or "").strip(),
        "guests": guests,
        "budget": as_decimal(budget),
        "service": str(data.get("service") or "").strip()[:100],
        "notes": str(data.get("notes") or "").strip(),
        "terms_accepted": data.get("termsAccepted") is True,
    }


def submit_inquiry(data):
    fields = _clean(data)
    for attempt in range(REFERENCE_ATTEMPTS):
        lock_date(fields["event_date"])
        if is_unavailable(fields["event_date"]):
            reject("That date is no longer available. Please choose another date.", 409, rollback=True)
        if not fields["terms_accepted"]:
            reject("Please agree to the inquiry terms before submitting.", rollback=True)
        inquiry = Inquiry(
            id="inq-" + secrets.token_urlsafe(10),
            reference=new_reference(),
            status="Submitted",
            **fields,
        )
        db.session.add(inquiry)
        try:
            db.session.commit()
            break
        except IntegrityError:
            # Reference codes are random; on the rare collision, try again.
            db.session.rollback()
            if attempt == REFERENCE_ATTEMPTS - 1:
                raise
    notify_client(inquiry.to_dict(), "Submitted")
    return inquiry


def find_by_reference(code):
    code = str(code or "").strip().upper()
    return db.session.scalar(select(Inquiry).where(Inquiry.reference == code))


def change_status(inquiry_id, status, expected_revenue):
    if status not in STATUSES:
        reject("Choose a valid inquiry status.")
    inquiry = db.session.get(Inquiry, inquiry_id)
    if inquiry is None:
        reject("Inquiry not found.", 404)
    booking = db.session.scalar(select(Booking).where(Booking.inquiry_id == inquiry_id))
    if status == "Approved" and (not booking or booking.status != "Confirmed"):
        if inquiry.event_date < date.today():
            reject("This event date has passed.", 409)
        lock_date(inquiry.event_date)
        if is_unavailable(inquiry.event_date):
            reject("This date is already booked or unavailable.", 409, rollback=True)
        try:
            revenue = float(expected_revenue or 0)
        except (TypeError, ValueError):
            reject("Expected revenue must be a valid number.", rollback=True)
        if not 0 <= revenue <= 1_000_000_000:
            reject("Expected revenue must be a valid non-negative amount.", rollback=True)
        if booking:
            booking.status = "Confirmed"
            booking.expected_revenue = as_decimal(revenue)
        else:
            db.session.add(
                Booking(
                    id="booking-" + secrets.token_urlsafe(10),
                    inquiry_id=inquiry.id,
                    client_name=inquiry.name,
                    event_name=inquiry.event_name,
                    date=inquiry.event_date,
                    venue=inquiry.venue or "",
                    status="Confirmed",
                    expected_revenue=as_decimal(revenue),
                    actual_revenue=None,
                )
            )
    elif booking and status in {"Declined", "Cancelled"} and booking.status == "Confirmed":
        booking.status = "Cancelled"
    previous_status = inquiry.status
    inquiry.status = status
    db.session.commit()
    if previous_status != status:
        notify_client(inquiry.to_dict(), status)
    return inquiry
