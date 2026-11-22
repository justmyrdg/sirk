"""Admin workspace pages: dashboard, inquiries, schedule, services,
analytics, landing page. Admin host only, signed-in admins only."""

from datetime import date

from flask import Blueprint, abort, flash, g, redirect, request
from sqlalchemy import select

from fipconnect.controllers.admin_pages import admin_page
from fipconnect.extensions import db
from fipconnect.models import STATUSES, Block, Booking, Inquiry, Service, SiteSettings
from fipconnect.services import catalog, inquiries, metrics, schedule
from fipconnect.services.analytics import analytics
from fipconnect.services.calendar import calendar_weeks, month_from_param, shift_month
from fipconnect.services.errors import ValidationError
from fipconnect.services.security import SESSION_EXPIRED, page_admin_required
from fipconnect.views import month_short, peso

bp = Blueprint("workspace_pages", __name__)


# ---- helpers ------------------------------------------------------------------

def all_inquiries():
    return db.session.scalars(select(Inquiry).order_by(Inquiry.created_at.desc())).all()


def all_bookings():
    return db.session.scalars(select(Booking).order_by(Booking.date, Booking.id)).all()


def report_for(inquiry_rows, booking_rows):
    return analytics([item.to_dict() for item in inquiry_rows], [item.to_dict() for item in booking_rows])


def plain_amount(value, empty=""):
    """A Decimal as the user would type it: 12000 or 12000.5."""
    if value is None:
        return empty
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def handle_form(render_again, action, success_message, target):
    """Shared POST flow: refuse a stale CSRF token, run the action, and
    re-render with the rule's message (and status) if it is refused."""
    if g.get("csrf_failed"):
        return render_again(SESSION_EXPIRED, 400)
    try:
        result = action()
    except ValidationError as error:
        db.session.rollback()
        return render_again(error.message, error.status)
    flash(success_message(result) if callable(success_message) else success_message, "success")
    return redirect(target, code=303)


# ---- dashboard ----------------------------------------------------------------

def dashboard():
    inquiry_rows = all_inquiries()
    booking_rows = all_bookings()
    today = metrics.local_today()
    per_month = metrics.inquiries_per_month(inquiry_rows, today)
    revenue = metrics.revenue_per_month(booking_rows, today)
    outlook = metrics.forecast(inquiry_rows, booking_rows, today)
    return admin_page(
        "admin/dashboard.html", active_tab="Dashboard",
        kpis=metrics.kpis(inquiry_rows, booking_rows, today),
        recent=inquiry_rows[:5],
        charts=dashboard_charts(per_month, revenue, outlook),
        outlook=outlook,
    )


def dashboard_charts(per_month, revenue, outlook):
    """Chart data for the dashboard, each with a one-line summary and an
    empty message when there is nothing to draw."""
    total = sum(per_month["counts"])
    busiest = max(zip(per_month["counts"], per_month["labels"])) if total else None
    expected_total = sum(revenue["expected"])
    actual_total = sum(revenue["actual"])
    pipeline_total = sum(outlook["pipeline"]["expected"])
    charts = {
        "inquiries": {
            "data": {"kind": "line", "format": "count", "labels": per_month["labels"],
                     "series": [{"name": "Inquiries received", "values": per_month["counts"]}]},
            "summary": (f"{total} inquiries in the last 12 months; busiest month "
                        f"{month_short(busiest[1])} with {busiest[0]}.") if total else "",
            "empty": None if total else "No inquiries in the last 12 months yet.",
        },
        "revenue": {
            "data": {"kind": "bar", "format": "peso", "labels": revenue["labels"],
                     "series": [{"name": "Booked (expected)", "values": revenue["expected"]},
                                {"name": "Completed (actual)", "values": revenue["actual"]}]},
            "summary": (f"{peso(expected_total)} booked and {peso(actual_total)} completed "
                        "across the last 12 months, by event month."),
            "empty": None if expected_total or actual_total else "No booked or completed revenue in the last 12 months yet.",
        },
        "pipeline": {
            "data": {"kind": "bar", "format": "peso", "labels": outlook["pipeline"]["labels"],
                     "series": [{"name": "Confirmed bookings (expected)", "values": outlook["pipeline"]["expected"]}]},
            "summary": f"{peso(pipeline_total)} expected from confirmed bookings in the next 6 months.",
            "empty": None if pipeline_total else "No confirmed bookings in the next 6 months yet.",
        },
    }
    projection = outlook["projection"]
    if projection is None:
        charts["projection"] = {
            "data": None,
            "summary": "",
            "empty": (f"Forecast available after {outlook['min_history']} months of data "
                      f"({outlook['months_of_history']} so far)."),
        }
    else:
        # History stops at the last complete month, the same months the
        # projection is based on; the current month is still filling up.
        history_labels = per_month["labels"][-7:-1]
        history_values = per_month["counts"][-7:-1]
        labels = history_labels + projection["labels"]
        future = len(projection["labels"])
        charts["projection"] = {
            "data": {
                "kind": "forecast", "format": "count", "labels": labels,
                "series": [
                    {"name": "Inquiries received", "values": history_values + [None] * future},
                    {"name": "Projected", "values": [None] * len(history_values) + [projection["estimate"]] * future},
                ],
                "range": {"low": projection["low"], "high": projection["high"], "from": len(history_values)},
            },
            "summary": (f"About {projection['estimate']:g} inquiries a month expected over the next "
                        f"{future} months (likely {projection['low']}–{projection['high']}), based on the "
                        "average of the last 3 complete months."),
            "empty": None,
        }
    return charts


# ---- inquiries ----------------------------------------------------------------

@bp.get("/inquiries")
@page_admin_required
def inquiry_list():
    return admin_page("admin/inquiries.html", active_tab="Inquiries", items=all_inquiries())


def review_page(inquiry_id, form, error=None, status=200):
    inquiry = db.session.get(Inquiry, inquiry_id) or abort(404)
    return admin_page("admin/inquiry_review.html", status, active_tab="Inquiries",
                      inquiry=inquiry, form=form, statuses=STATUSES, error=error)


@bp.get("/inquiries/<inquiry_id>")
@page_admin_required
def inquiry_review(inquiry_id):
    inquiry = db.session.get(Inquiry, inquiry_id) or abort(404)
    return review_page(inquiry_id, {"status": inquiry.status, "expectedRevenue": plain_amount(inquiry.budget)})


@bp.post("/inquiries/<inquiry_id>")
@page_admin_required
def inquiry_update(inquiry_id):
    db.session.get(Inquiry, inquiry_id) or abort(404)
    form = {"status": request.form.get("status", ""), "expectedRevenue": request.form.get("expectedRevenue", "")}
    return handle_form(
        lambda message, status: review_page(inquiry_id, form, message, status),
        lambda: inquiries.change_status(inquiry_id, form["status"], form["expectedRevenue"]),
        "Inquiry updated.", "/inquiries",
    )


# ---- schedule -----------------------------------------------------------------

def schedule_view(form=None, error=None, status=200):
    month_start = month_from_param(request.args.get("month"), date.today())
    booking_rows = all_bookings()
    blocks = db.session.scalars(select(Block).order_by(Block.date)).all()
    counts = {}
    for item in all_inquiries():
        if item.status not in ("Declined", "Cancelled"):
            key = item.event_date.isoformat()
            counts[key] = counts.get(key, 0) + 1
    return admin_page(
        "admin/schedule.html", status, active_tab="Schedule", error=error,
        form=form or {"date": "", "reason": ""},
        month_start=month_start, weeks=calendar_weeks(month_start),
        prev_month=shift_month(month_start, -1), next_month=shift_month(month_start, 1),
        booked_dates={item.date.isoformat() for item in booking_rows if item.status == "Confirmed"},
        blocked_dates={item.date.isoformat() for item in blocks},
        inquiry_counts=counts, bookings=booking_rows, blocks=blocks,
        confirmed_count=sum(item.status == "Confirmed" for item in booking_rows),
    )


@bp.get("/schedule")
@page_admin_required
def schedule_page():
    return schedule_view()


@bp.post("/blocks")
@page_admin_required
def block_create():
    form = {"date": request.form.get("date", ""), "reason": request.form.get("reason", "")}
    return handle_form(
        lambda message, status: schedule_view(form, message, status),
        lambda: schedule.block_date(form["date"], form["reason"]),
        "Date blocked.", "/schedule",
    )


@bp.post("/blocks/<block_id>/delete")
@page_admin_required
def block_delete(block_id):
    return handle_form(
        lambda message, status: schedule_view(None, message, status),
        lambda: schedule.unblock(block_id),
        "Date unblocked.", "/schedule",
    )


def complete_view(booking_id, form, error=None, status=200):
    booking = db.session.get(Booking, booking_id) or abort(404)
    return admin_page("admin/booking_complete.html", status, active_tab="Schedule",
                      booking=booking, form=form, error=error)


@bp.get("/bookings/<booking_id>/complete")
@page_admin_required
def booking_complete_page(booking_id):
    booking = db.session.get(Booking, booking_id) or abort(404)
    return complete_view(booking_id, {"actualRevenue": plain_amount(booking.expected_revenue, "0")})


@bp.post("/bookings/<booking_id>/complete")
@page_admin_required
def booking_complete(booking_id):
    db.session.get(Booking, booking_id) or abort(404)
    form = {"actualRevenue": request.form.get("actualRevenue", "")}
    return handle_form(
        lambda message, status: complete_view(booking_id, form, message, status),
        lambda: schedule.complete_booking(booking_id, form["actualRevenue"]),
        "Booking completed.", "/schedule",
    )


# ---- services -----------------------------------------------------------------

def services_view(form=None, error=None, status=200):
    services = db.session.scalars(select(Service).order_by(Service.position)).all()
    return admin_page("admin/services.html", status, active_tab="Services", services=services,
                      form=form or {"name": "", "description": ""}, error=error)


@bp.get("/services")
@page_admin_required
def services_page():
    return services_view()


@bp.post("/services")
@page_admin_required
def service_create():
    form = {"name": request.form.get("name", ""), "description": request.form.get("description", "")}
    return handle_form(
        lambda message, status: services_view(form, message, status),
        lambda: catalog.add_service(form["name"], form["description"]),
        "Service added.", "/services",
    )


def service_edit_view(service_id, form, error=None, status=200):
    service = db.session.get(Service, service_id) or abort(404)
    return admin_page("admin/service_edit.html", status, active_tab="Services",
                      service=service, form=form, error=error)


@bp.get("/services/<service_id>/edit")
@page_admin_required
def service_edit_page(service_id):
    service = db.session.get(Service, service_id) or abort(404)
    return service_edit_view(service_id, {"name": service.name, "description": service.description})


@bp.post("/services/<service_id>/edit")
@page_admin_required
def service_edit(service_id):
    db.session.get(Service, service_id) or abort(404)
    form = {"name": request.form.get("name", ""), "description": request.form.get("description", "")}
    return handle_form(
        lambda message, status: service_edit_view(service_id, form, message, status),
        lambda: catalog.edit_service(service_id, form["name"], form["description"]),
        "Service saved.", "/services",
    )


@bp.post("/services/<service_id>/toggle")
@page_admin_required
def service_toggle(service_id):
    service = db.session.get(Service, service_id) or abort(404)
    make_active = not service.active
    return handle_form(
        lambda message, status: services_view(None, message, status),
        lambda: catalog.set_service_active(service_id, make_active),
        lambda updated: "Service published." if updated.active else "Service hidden.",
        "/services",
    )


@bp.post("/services/<service_id>/delete")
@page_admin_required
def service_delete(service_id):
    return handle_form(
        lambda message, status: services_view(None, message, status),
        lambda: catalog.delete_service(service_id),
        "Service deleted.", "/services",
    )


# ---- analytics & landing --------------------------------------------------------

@bp.get("/analytics")
@page_admin_required
def analytics_page():
    inquiry_rows = all_inquiries()
    booking_rows = all_bookings()
    report = report_for(inquiry_rows, booking_rows)
    booking_months = {}
    for item in booking_rows:
        if item.status in ("Confirmed", "Completed"):
            key = item.date.strftime("%Y-%m")
            booking_months[key] = booking_months.get(key, 0) + 1
    recent_booking_months = sorted(booking_months.items())[-12:]

    def count_chart(labels, values, name, kind="bar", label_format="month"):
        return {"kind": kind, "format": "count", "labelFormat": label_format,
                "labels": labels, "series": [{"name": name, "values": values}]}

    charts = {
        "event_months": count_chart(
            [item["month"] for item in report["inquiryMonths"]],
            [item["count"] for item in report["inquiryMonths"]],
            "Inquiries by event month",
        ),
        "event_types": count_chart(
            [item["name"] for item in report["eventTypes"]],
            [item["count"] for item in report["eventTypes"]],
            "Inquiries", kind="hbar", label_format="item",
        ),
        "booking_months": count_chart(
            [month for month, _ in recent_booking_months],
            [count for _, count in recent_booking_months],
            "Confirmed or completed bookings",
        ),
    }
    return admin_page(
        "admin/analytics.html", active_tab="Analytics",
        report=report,
        charts=charts,
        inquiry_count=len(inquiry_rows),
        booking_count=sum(item.status in ("Confirmed", "Completed") for item in booking_rows),
        bookings=booking_rows,
    )


def landing_view(form, error=None, status=200):
    return admin_page("admin/landing.html", status, active_tab="Landing page", form=form, error=error)


@bp.get("/landing")
@page_admin_required
def landing_page():
    return landing_view(db.session.get(SiteSettings, 1).to_dict())


@bp.post("/landing")
@page_admin_required
def landing_update():
    form = {field: request.form.get(field, "") for field in ("organizer", "headline", "intro")}
    return handle_form(
        lambda message, status: landing_view(form, message, status),
        lambda: catalog.update_landing(form["organizer"], form["headline"], form["intro"]),
        "Landing page updated.", "/landing",
    )
