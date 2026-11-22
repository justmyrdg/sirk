"""Client site pages (main domain only)."""

from functools import wraps

from flask import Blueprint, abort, current_app, flash, g, get_flashed_messages, redirect, render_template, request
from sqlalchemy import select

from fipconnect.extensions import db
from fipconnect.models import Service, SiteSettings
from fipconnect.services import inquiries
from fipconnect.services.availability import unavailable_dates
from fipconnect.services.calendar import calendar_weeks, month_from_param, shift_month
from fipconnect.services.errors import ValidationError
from fipconnect.services.metrics import local_today
from fipconnect.services.security import SESSION_EXPIRED, is_admin_host

bp = Blueprint("client_pages", __name__)

INQUIRY_FIELDS = ("name", "email", "phone", "eventName", "eventDate", "venue",
                  "guests", "budget", "service", "notes")


def client_host_only(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if is_admin_host():
            abort(404)
        return view(*args, **kwargs)

    return wrapped


def active_services():
    return db.session.scalars(
        select(Service).where(Service.active.is_(True)).order_by(Service.position)
    ).all()


def page(template, status=200, **context):
    context.setdefault("landing", db.session.get(SiteSettings, 1))
    context.setdefault("earliest", inquiries.earliest_bookable())
    context.setdefault("lead_days", current_app.config["MIN_LEAD_DAYS"])
    return render_template(template, **context), status


def home():
    return page("client/home.html", services=active_services())


@bp.get("/availability")
@client_host_only
def availability():
    month_start = month_from_param(request.args.get("month"), local_today())
    return page(
        "client/availability.html",
        month_start=month_start,
        weeks=calendar_weeks(month_start),
        prev_month=shift_month(month_start, -1),
        next_month=shift_month(month_start, 1),
        unavailable=unavailable_dates(),
    )


def inquiry_form(values, error=None, status=200):
    return page("client/inquire.html", status, form=values, error=error, services=active_services())


@bp.get("/inquire")
@client_host_only
def inquire():
    return inquiry_form({"eventDate": request.args.get("date", "")})


@bp.post("/inquire")
@client_host_only
def submit_inquiry():
    values = {field: request.form.get(field, "") for field in INQUIRY_FIELDS}
    values["terms"] = request.form.get("terms") == "on"
    if g.get("csrf_failed"):
        return inquiry_form(values, SESSION_EXPIRED, 400)
    try:
        inquiry = inquiries.submit_inquiry({**values, "termsAccepted": values["terms"]})
    except ValidationError as error:
        return inquiry_form(values, error.message, error.status)
    flash(inquiry.reference, "reference")
    flash(inquiry.name.split(" ")[0], "first_name")
    return redirect("/inquire/thanks", code=303)


@bp.get("/inquire/thanks")
@client_host_only
def thanks():
    messages = dict(get_flashed_messages(with_categories=True, category_filter=["reference", "first_name"]))
    if "reference" not in messages:
        return redirect("/inquire", code=303)
    return page("client/thanks.html", reference=messages["reference"], first_name=messages.get("first_name"))


@bp.get("/status")
@client_host_only
def status():
    return page("client/status.html", reference="", inquiry=None, error=None)


@bp.post("/status")
@client_host_only
def lookup_status():
    reference = request.form.get("reference", "").strip()
    if g.get("csrf_failed"):
        return page("client/status.html", 400, reference=reference, inquiry=None, error=SESSION_EXPIRED)
    inquiry = inquiries.find_by_reference(reference)
    if inquiry is None:
        return page("client/status.html", 404, reference=reference, inquiry=None,
                    error="No inquiry was found for that code.")
    return page("client/status.html", reference=reference, inquiry=inquiry, error=None)
