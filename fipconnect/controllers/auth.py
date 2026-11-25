"""Admin sign-in, first-time setup, adding admins, and face enrollment.
Every route here answers only on the admin host."""

from flask import Blueprint, current_app, jsonify, request, session
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash

from fipconnect.extensions import db
from fipconnect.models import Admin
from fipconnect.services import face, step_up
from fipconnect.services.accounts import admin_count, email_taken, new_admin
from fipconnect.services.availability import lock_setup
from fipconnect.services.security import (
    admin_host_only,
    admin_required,
    api_error,
    csrf_token,
    current_admin,
    pending_admin,
    require_csrf,
    sign_in,
    valid_admin_email,
)

bp = Blueprint("auth", __name__)

INVALID_ACCOUNT = "Enter a valid email and a password with at least 8 characters."
SETUP_DONE = "Administrator setup has already been completed."
CONFIRM_FIRST = "Confirm it's you first."
SIGN_IN_TIMED_OUT = "Sign-in timed out. Enter your password again."
RESET_NEEDS_OPERATOR = (
    "Your saved face can't be checked, so a face reset must first be allowed on the server: "
    "flask --app app allow-face-reset YOUR-EMAIL"
)


def read_account(payload):
    email = payload.get("email", "")
    password = payload.get("password", "")
    if not valid_admin_email(email) or not isinstance(password, str) or len(password) < 8:
        return None, None
    return email.strip().lower(), password


def extract_embedding(face_image):
    """Return (embedding, None) or (None, error_response)."""
    try:
        embedding = face.extract_face_embedding(
            face_image,
            current_app.config["FACE_SERVICE_URL"],
            face.face_service_token(current_app.secret_key),
        )
    except ValueError as error:
        return None, api_error(str(error), 400)
    except RuntimeError as error:
        return None, api_error(str(error), 503)
    return embedding, None


@bp.get("/api/admin/bootstrap")
@admin_host_only
def admin_bootstrap():
    return jsonify(
        {
            "adminConfigured": admin_count() > 0,
            "isAdmin": current_admin() is not None,
            "setupAllowed": bool(current_app.config["ALLOW_SETUP"]),
            "csrfToken": csrf_token(),
        }
    )


@bp.post("/api/setup-admin")
@admin_host_only
def setup_admin():
    csrf_failure = require_csrf()
    if csrf_failure:
        return csrf_failure
    payload = request.get_json(silent=True) or {}
    email, password = read_account(payload)
    if email is None:
        return api_error(INVALID_ACCOUNT)
    if admin_count() > 0:
        return api_error(SETUP_DONE, 409)
    if not current_app.config["ALLOW_SETUP"]:
        return api_error(
            "First-time setup is turned off. Set FIP_ALLOW_SETUP=true in .env, restart the app, and try again.",
            403,
        )
    # End the read transaction before the (slow) face service call.
    db.session.rollback()
    embedding, error = extract_embedding(payload.get("faceImage"))
    if error:
        return error
    lock_setup()
    if admin_count() > 0:
        db.session.rollback()
        return api_error(SETUP_DONE, 409)
    admin = new_admin(email, password, embedding)
    db.session.add(admin)
    db.session.commit()
    return jsonify({"ok": True, "csrfToken": sign_in(admin)})


@bp.post("/api/register-admin")
@admin_required
def register_admin():
    csrf_failure = require_csrf()
    if csrf_failure:
        return csrf_failure
    signed_in_admin = current_admin()
    if not step_up.is_fresh(signed_in_admin):
        return api_error(CONFIRM_FIRST, 403)
    if not step_up.is_fresh(signed_in_admin, require_face=True):
        return api_error("Adding an admin needs a face confirmation.", 403)
    admin_id = signed_in_admin.id
    payload = request.get_json(silent=True) or {}
    email, password = read_account(payload)
    if email is None:
        return api_error(INVALID_ACCOUNT)
    duplicate = "An administrator account with this email already exists."
    if email_taken(email):
        return api_error(duplicate, 409)
    db.session.rollback()
    embedding, error = extract_embedding(payload.get("faceImage"))
    if error:
        return error
    if email_taken(email):
        return api_error(duplicate, 409)
    if not step_up.consume(admin_id):
        # Already used: a replayed cookie or a request racing this one.
        db.session.rollback()
        return api_error(CONFIRM_FIRST, 403)
    db.session.add(new_admin(email, password, embedding))
    try:
        db.session.commit()
    except IntegrityError:
        # Someone added the same email while the face scan was running.
        db.session.rollback()
        return api_error(duplicate, 409)
    step_up.forget()
    return jsonify({"ok": True})


@bp.post("/api/login/face")
@admin_host_only
def login_face():
    csrf_failure = require_csrf()
    if csrf_failure:
        return csrf_failure
    # Step 2 of signing in: the password was accepted (pending sign-in); the
    # photo must match that account's own saved face.
    admin = pending_admin()
    if admin is None or not step_up.has_usable_face(admin):
        return api_error(SIGN_IN_TIMED_OUT, 401)
    locked = locked_response(admin)
    if locked:
        return locked
    admin_id = admin.id
    payload = request.get_json(silent=True) or {}
    try:
        own_embedding = face.decrypt_face_embedding(current_app.secret_key, admin.face_embedding)
        db.session.rollback()
        verified = face.verify_face_embedding(
            payload.get("faceImage"),
            own_embedding,
            current_app.config["FACE_SERVICE_URL"],
            face.face_service_token(current_app.secret_key),
        )
    except ValueError as error:
        return api_error(str(error), 400)
    except RuntimeError as error:
        return api_error(str(error), 503)
    admin = db.session.get(Admin, admin_id)
    if admin is None:
        return api_error(SIGN_IN_TIMED_OUT, 401)
    if not verified:
        step_up.record_failure(admin)
        return api_error("Face not recognized. Please try again.", 401)
    step_up.clear_failures(admin)
    return jsonify({"ok": True, "csrfToken": sign_in(admin)})


@bp.post("/api/admin/face")
@admin_required
def update_admin_face():
    csrf_failure = require_csrf()
    if csrf_failure:
        return csrf_failure
    if not step_up.is_fresh(current_admin()):
        return api_error(CONFIRM_FIRST, 403)
    payload = request.get_json(silent=True) or {}
    admin_id = session.get("admin_id")
    db.session.rollback()
    embedding, error = extract_embedding(payload.get("faceImage"))
    if error:
        return error
    admin = db.session.get(Admin, admin_id)
    if admin is None:
        return api_error("Sign in again before updating your face template.", 401)
    if not step_up.consume(admin_id):
        db.session.rollback()
        return api_error(CONFIRM_FIRST, 403)
    admin = db.session.get(Admin, admin_id)
    admin.face_embedding = face.encrypt_face_embedding(current_app.secret_key, embedding)
    admin.face_model = face.FACE_MODEL
    admin.face_reset_until = None  # an operator's reset allowance is used up too
    db.session.commit()
    step_up.forget()
    return jsonify({"ok": True})


# ---- "Confirm it's you" before adding an admin or re-enrolling a face -------

@bp.post("/api/admin/verify-face")
@admin_required
def verify_own_face():
    csrf_failure = require_csrf()
    if csrf_failure:
        return csrf_failure
    admin = current_admin()
    locked = locked_response(admin)
    if locked:
        return locked
    if not step_up.has_usable_face(admin):
        return api_error("Your saved face can't be checked. Confirm with your password.", 409)
    admin_id = admin.id
    payload = request.get_json(silent=True) or {}
    try:
        # Only the signed-in admin's own saved face counts.
        own_embedding = face.decrypt_face_embedding(current_app.secret_key, admin.face_embedding)
        db.session.rollback()
        verified = face.verify_face_embedding(
            payload.get("faceImage"),
            own_embedding,
            current_app.config["FACE_SERVICE_URL"],
            face.face_service_token(current_app.secret_key),
        )
    except ValueError as error:
        return api_error(str(error), 400)
    except RuntimeError as error:
        return api_error(str(error), 503)
    admin = db.session.get(Admin, admin_id)
    if not verified:
        step_up.record_failure(admin)
        return api_error("Face not recognized. Please try again.", 401)
    step_up.mark_verified(admin, step_up.FACE)
    return jsonify({"ok": True, "secondsLeft": step_up.seconds_left(admin)})


@bp.post("/api/admin/verify-password")
@admin_required
def verify_own_password():
    csrf_failure = require_csrf()
    if csrf_failure:
        return csrf_failure
    admin = current_admin()
    locked = locked_response(admin)
    if locked:
        return locked
    if step_up.has_usable_face(admin):
        return api_error("Use a face scan to confirm it's you.", 403)
    if not step_up.reset_allowed(admin):
        return api_error(RESET_NEEDS_OPERATOR, 403)
    payload = request.get_json(silent=True) or {}
    password = payload.get("password", "")
    if not isinstance(password, str) or not check_password_hash(admin.password_hash, password):
        step_up.record_failure(admin)
        return api_error("Incorrect password.", 401)
    step_up.mark_verified(admin, step_up.PASSWORD)
    return jsonify({"ok": True, "secondsLeft": step_up.seconds_left(admin)})


def locked_response(admin):
    seconds = step_up.locked_seconds(admin)
    if not seconds:
        return None
    minutes = max(1, (seconds + 59) // 60)
    return api_error(
        f"Too many attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.", 429
    )


