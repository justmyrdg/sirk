"""Month grids for the availability and schedule calendars."""

import calendar as _calendar
from datetime import date

_SUNDAY_FIRST = _calendar.Calendar(firstweekday=6)


# Months a calendar can show. Wider years would overflow when the page
# links to the previous/next month, so anything outside falls back.
MIN_YEAR, MAX_YEAR = 1900, 9998


def month_from_param(value, today):
    """First day of the month in a `YYYY-MM` query value, else today's month."""
    try:
        year_text, month_text = str(value or "").split("-")
        month_start = date(int(year_text), int(month_text), 1)
    except ValueError:
        month_start = None
    if month_start is None or not MIN_YEAR <= month_start.year <= MAX_YEAR:
        return date(today.year, today.month, 1)
    return month_start


def shift_month(month_start, delta):
    index = month_start.year * 12 + (month_start.month - 1) + delta
    return date(index // 12, index % 12 + 1, 1)


def calendar_weeks(month_start):
    """Weeks (Sunday first) of the month; days outside it are None."""
    return [
        [day if day.month == month_start.month else None for day in week]
        for week in _SUNDAY_FIRST.monthdatescalendar(month_start.year, month_start.month)
    ]
