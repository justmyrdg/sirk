"""Admin site pages (admin host only)."""

from flask import Blueprint, current_app, g, redirect, render_template, request, session

from fipconnect.services import step_up
from fipconnect.services.accounts import admin_count, authenticate
from fipconnect.services.security import (
    SESSION_EXPIRED,
    admin_page_host,
    current_admin,
    page_admin_required,
    sign_in,
)

bp = Blueprint("admin_pages", __name__)


def admin_page(template, status=200, **context):
    context.setdefault("current_admin", current_admin())
    context.setdefault("client_url", current_app.config["CLIENT_URL"])
    context.setdefault("error", None)
    return render_template(template, **context), status


# ---- Sign-in, setup, sign-out ---------------------------------------------

@bp.get("/login")
@admin_page_host
def login():
    if admin_count() == 0:
        return redirect("/setup", code=303)
    if current_admin() is not None:
        return redirect("/", code=303)
    return admin_page("admin/login.html", email="")


@bp.post("/login")
@admin_page_host
def login_submit():
    email = request.form.get("email", "").strip()
    if g.get("csrf_failed"):
        return admin_page("admin/login.html", 400, email=email, error=SESSION_EXPIRED)
    admin = authenticate(email, request.form.get("password", ""))
    if admin is None:
        return admin_page("admin/login.html", 401, email=email, error="Incorrect email or password.")
    sign_in(admin)
    return redirect("/", code=303)


@bp.post("/logout")
@admin_page_host
def logout():
    # Always sign out, even with an outdated form token (e.g. the admin signed
    # in again in another tab): someone pressing "Log out" must end up signed
    # out, and a forged logout can do no harm beyond that.
    session.clear()
    return redirect("/login", code=303)


@bp.get("/setup")
@admin_page_host
def setup():
    if admin_count() > 0:
        return redirect("/login", code=303)
    if not current_app.config["ALLOW_SETUP"]:
        return admin_page("admin/setup_off.html")
    return admin_page("admin/setup.html")


# ---- Account pages (camera) -------------------------------------------------

@bp.get("/admins/new")
@page_admin_required
def new_admin():
    return admin_page("admin/admin_new.html", added=request.args.get("added") == "1", **step_up_context())


@bp.get("/account/face")
@page_admin_required
def face_enroll():
    return admin_page("admin/face_enroll.html", updated=request.args.get("updated") == "1", **step_up_context())


def step_up_context():
    """Whether the 'confirm it's you' step is done, and how it can be done."""
    admin = current_admin()
    return {
        "step_up_left": step_up.seconds_left(admin),
        "step_up_method": step_up.method(),
        "usable_face": step_up.has_usable_face(admin),
        "reset_allowed": step_up.reset_allowed(admin),
    }
