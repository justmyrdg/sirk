"""Template helpers (the "V" in MVC): filters and globals for Jinja pages."""

from datetime import date
from decimal import Decimal

from fipconnect.services.metrics import local_today
from fipconnect.services.security import csrf_token

_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def _as_date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def date_ph(value):
    """Nov 16, 2027"""
    day = _as_date(value)
    return "" if day is None else f"{_MONTHS[day.month - 1][:3]} {day.day}, {day.year}"


def date_long(value):
    """Sat, Nov 29, 2026"""
    day = _as_date(value)
    if day is None:
        return ""
    weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day.weekday()]
    return f"{weekday}, {date_ph(day)}"


def month_ph(value):
    """November 2027"""
    day = _as_date(value)
    return "" if day is None else f"{_MONTHS[day.month - 1]} {day.year}"


def month_short(value):
    """Nov 27 (used on analytics bars)"""
    day = _as_date(f"{value}-01" if isinstance(value, str) and len(value) == 7 else value)
    return "" if day is None else f"{_MONTHS[day.month - 1][:3]} {str(day.year)[2:]}"


def peso(value):
    """₱12,000 — centavos only when not zero; — for no amount."""
    if value is None or value == "":
        return "—"
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    if amount == amount.to_integral_value():
        return f"₱{int(amount):,}"
    return f"₱{amount:,.2f}"


def register_views(app):
    app.jinja_env.filters.update(
        date_ph=date_ph, date_long=date_long, month_ph=month_ph, month_short=month_short, peso=peso
    )
    # "today" in pages is the Philippine date, matching the booking rules.
    app.jinja_env.globals.update(csrf_token=csrf_token, today=local_today)
