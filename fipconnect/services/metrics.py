"""Dashboard numbers: KPIs, monthly series and a forecast.

Pure functions over model rows (anything with the model's attribute names),
so they are easy to test with fixed dates. Months are "YYYY-MM" strings.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fipconnect.models import PENDING_STATUSES

# Months and "today" follow Philippine time (UTC+8, no daylight saving), so an
# inquiry sent at 7am on the 1st counts in that month wherever the server runs.
PH_TIME = timezone(timedelta(hours=8))

SERIES_MONTHS = 12
PIPELINE_MONTHS = 6
PROJECTION_MONTHS = 3
MIN_HISTORY_FOR_PROJECTION = 6


def _month_key(day):
    return f"{day.year:04d}-{day.month:02d}"


def _shift(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def month_keys(today, count=SERIES_MONTHS):
    """The last `count` months, oldest first, ending with today's month."""
    return [
        "{:04d}-{:02d}".format(*_shift(today.year, today.month, offset))
        for offset in range(-(count - 1), 1)
    ]


def _future_keys(today, count, start_offset):
    return [
        "{:04d}-{:02d}".format(*_shift(today.year, today.month, offset))
        for offset in range(start_offset, start_offset + count)
    ]


def local_today(now=None):
    """Today's date in the Philippines."""
    return (now or datetime.now(timezone.utc)).astimezone(PH_TIME).date()


def _created_day(inquiry):
    created = inquiry.created_at
    if isinstance(created, datetime):
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return created.astimezone(PH_TIME).date()
    return created


def _conversion(inquiries, bookings):
    """Share of resolved inquiries that became bookings (same rule as Analytics)."""
    resolved = [item for item in inquiries if item.status not in PENDING_STATUSES]
    if not resolved:
        return 0
    booked_ids = {
        item.inquiry_id for item in bookings if item.status in {"Confirmed", "Completed"}
    }
    converted = sum(item.status == "Approved" or item.id in booked_ids for item in resolved)
    return round(converted / len(resolved) * 100)


def kpis(inquiries, bookings, today):
    this_month = _month_key(today)
    upcoming = [item for item in bookings if item.status == "Confirmed" and item.date >= today]
    return {
        "total": len(inquiries),
        "this_month": sum(_month_key(_created_day(item)) == this_month for item in inquiries),
        "pending": sum(item.status in PENDING_STATUSES for item in inquiries),
        "upcoming": len(upcoming),
        "conversion": _conversion(inquiries, bookings),
        "expected_upcoming": sum((item.expected_revenue or Decimal(0) for item in upcoming), Decimal(0)),
        "actual_completed": sum(
            (item.actual_revenue or Decimal(0) for item in bookings if item.status == "Completed"),
            Decimal(0),
        ),
    }


def inquiries_per_month(inquiries, today):
    labels = month_keys(today)
    counts = dict.fromkeys(labels, 0)
    for item in inquiries:
        key = _month_key(_created_day(item))
        if key in counts:
            counts[key] += 1
    return {"labels": labels, "counts": [counts[key] for key in labels]}


def revenue_per_month(bookings, today):
    labels = month_keys(today)
    expected = dict.fromkeys(labels, 0.0)
    actual = dict.fromkeys(labels, 0.0)
    for item in bookings:
        key = _month_key(item.date)
        if key not in expected:
            continue
        if item.status in {"Confirmed", "Completed"}:
            expected[key] += float(item.expected_revenue or 0)
        if item.status == "Completed":
            actual[key] += float(item.actual_revenue or 0)
    return {
        "labels": labels,
        "expected": [expected[key] for key in labels],
        "actual": [actual[key] for key in labels],
    }


def _complete_months_since_first(inquiries, today):
    if not inquiries:
        return 0
    first = min(_created_day(item) for item in inquiries)
    return max(0, (today.year - first.year) * 12 + (today.month - first.month))


def forecast(inquiries, bookings, today):
    """Confirmed pipeline (real numbers) and, with enough history, a simple
    inquiry projection: the average of the last 3 complete months, with the
    lowest and highest of those months as the likely range."""
    pipeline_labels = _future_keys(today, PIPELINE_MONTHS, 0)
    pipeline = dict.fromkeys(pipeline_labels, 0.0)
    for item in bookings:
        key = _month_key(item.date)
        if item.status == "Confirmed" and item.date >= today and key in pipeline:
            pipeline[key] += float(item.expected_revenue or 0)

    history = _complete_months_since_first(inquiries, today)
    projection = None
    if history >= MIN_HISTORY_FOR_PROJECTION:
        recent_keys = _future_keys(today, PROJECTION_MONTHS, -PROJECTION_MONTHS)
        counts = dict.fromkeys(recent_keys, 0)
        for item in inquiries:
            key = _month_key(_created_day(item))
            if key in counts:
                counts[key] += 1
        values = [counts[key] for key in recent_keys]
        projection = {
            "labels": _future_keys(today, PROJECTION_MONTHS, 1),
            "basis": recent_keys,
            "estimate": round(sum(values) / len(values), 1),
            "low": min(values),
            "high": max(values),
        }
    return {
        "pipeline": {"labels": pipeline_labels, "expected": [pipeline[key] for key in pipeline_labels]},
        "months_of_history": history,
        "min_history": MIN_HISTORY_FOR_PROJECTION,
        "projection": projection,
    }

