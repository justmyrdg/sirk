"""Admin-host checks, CSRF tokens, and admin session helpers."""

import ipaddress
import re
import secrets
import time
from functools import wraps
from urllib.parse import urlsplit

from flask import abort, current_app, g, jsonify, redirect, request, session

from fipconnect.extensions import db
from fipconnect.models import Admin


def api_error(message, status=400):
    return jsonify({"error": message}), status


def is_admin_host():
    hostname = urlsplit(f"//{request.host}").hostname or ""
    if hostname.lower() != current_app.config["ADMIN_HOST"]:
        return False
    if not current_app.config["ADMIN_HOST_LOCAL_ONLY"]:
        return True
    try:
        return ipaddress.ip_address(request.remote_addr or "").is_loopback
    except ValueError:
        return False


def admin_host_only(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin_host():
            return api_error("Not found.", 404)
        return view(*args, **kwargs)

    return wrapped


def current_admin():
    admin_id = session.get("admin_id")
    if not isinstance(admin_id, int):
        return None
    return db.session.get(Admin, admin_id)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin_host():
            return api_error("Not found.", 404)
        if current_admin() is None:
            return api_error("Administrator sign-in is required.", 401)
        if _blocked_by_enrollment(view):
            return api_error(ENROLL_FIRST, 403)
        return view(*args, **kwargs)

    return wrapped


def sign_in(admin, enroll_only=False):
    session.clear()
    session["admin_id"] = admin.id
    if enroll_only:
        session["must_enroll_face"] = True
    return csrf_token()


# ---- Enroll-only sign-in: the account has no face that can be checked ----------
# Until a face is saved, only views marked with enroll_only_ok work.

ENROLL_FIRST = "Enroll your face first."


def is_enroll_only():
    return session.get("must_enroll_face") is True


def enroll_only_ok(view):
    """Mark a view as usable while the admin must still enroll a face.
    Put it below @admin_required / @page_admin_required."""
    view.enroll_only_ok = True
    return view


def _blocked_by_enrollment(view):
    return is_enroll_only() and not getattr(view, "enroll_only_ok", False)


# ---- Pending sign-in: password accepted, face scan still to do ---------------
# The session holds no admin_id yet, so every admin guard treats it as signed out.

PENDING_WINDOW = 300  # seconds to finish the face scan after the password


def now():
    return time.time()


def begin_pending(admin):
    session.clear()
    session["pending_admin_id"] = admin.id
    session["pending_at"] = now()
    return csrf_token()


def pending_admin():
    admin_id = session.get("pending_admin_id")
    started = session.get("pending_at")
    if not isinstance(admin_id, int) or not isinstance(started, (int, float)):
        return None
    if now() - started >= PENDING_WINDOW:
        return None
    return db.session.get(Admin, admin_id)


def csrf_token():
    token = session.get("csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def require_csrf():
    expected = session.get("csrf_token", "")
    supplied = request.headers.get("X-CSRF-Token", "")
    if not expected or not secrets.compare_digest(expected, supplied):
        return api_error("Your session expired. Refresh the page and try again.", 400)
    return None


def valid_admin_email(value):
    return (
        isinstance(value, str)
        and len(value) <= 254
        and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) is not None
    )


def wants_json():
    return request.path.startswith("/api/")


SESSION_EXPIRED = "Your session expired. Refresh the page and try again."


def csrf_protect():
    """before_request: flag page form posts whose token doesn't match.
    API routes check their own X-CSRF-Token header."""
    if request.method in {"GET", "HEAD", "OPTIONS"} or wants_json():
        return None
    expected = session.get("csrf_token", "")
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    g.csrf_failed = not expected or not secrets.compare_digest(expected, supplied)
    return None


def page_admin_required(view):
    """Admin pages: 404 off the admin host; otherwise send signed-out
    visitors to setup (no admins yet) or to the login page."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin_host():
            abort(404)
        if current_admin() is None:
            from fipconnect.services.accounts import admin_count

            return redirect("/setup" if admin_count() == 0 else "/login")
        if _blocked_by_enrollment(view):
            return redirect("/account/face", code=303)
        return view(*args, **kwargs)

    return wrapped


def admin_page_host(view):
    """Admin pages that don't need a session (login, setup): 404 elsewhere."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin_host():
            abort(404)
        return view(*args, **kwargs)

    return wrapped
