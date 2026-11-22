"""Dashboard analytics computed from inquiry and booking records."""

from fipconnect.models import PENDING_STATUSES


def analytics(inquiries, bookings):
    """Descriptive summaries for the admin dashboard, from API-shaped dicts."""
    resolved = [item for item in inquiries if item.get("status") not in PENDING_STATUSES]
    converted = sum(
        1
        for item in resolved
        if item.get("status") == "Approved"
        or any(
            booking.get("inquiryId") == item.get("id")
            and booking.get("status") in {"Confirmed", "Completed"}
            for booking in bookings
        )
    )
    inquiry_months = {}
    for item in inquiries:
        event_month = item.get("eventDate", "")[:7]
        if event_month:
            inquiry_months[event_month] = inquiry_months.get(event_month, 0) + 1
    type_counts = {}
    for item in inquiries:
        event_type = item.get("eventName", "Other")
        type_counts[event_type] = type_counts.get(event_type, 0) + 1
    booking_months = {}
    for item in bookings:
        if item.get("status") not in {"Confirmed", "Completed"}:
            continue
        month = item.get("date", "")[:7]
        if month:
            booking_months[month] = booking_months.get(month, 0) + 1
    peak_month = max(booking_months, key=booking_months.get) if booking_months else None
    actual_revenue = sum(
        float(item.get("actualRevenue") or 0)
        for item in bookings
        if item.get("status") == "Completed"
    )
    return {
        "inquiryMonths": [
            {"month": month, "count": count}
            for month, count in sorted(inquiry_months.items())[-6:]
        ],
        "eventTypes": [
            {"name": name, "count": count}
            for name, count in sorted(
                type_counts.items(), key=lambda pair: (-pair[1], pair[0])
            )[:6]
        ],
        "peakBookingMonth": peak_month,
        "peakBookingCount": booking_months.get(peak_month, 0) if peak_month else 0,
        "conversionRate": round(converted / len(resolved) * 100) if resolved else 0,
        "actualRevenue": actual_revenue,
    }
