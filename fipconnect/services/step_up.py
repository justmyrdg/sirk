"""'Confirm it's you' checks before sensitive admin actions.

A signed-in admin proves it is really them with a live face scan matched
against their own saved face. The proof lasts a short window and is used up
by the one action it allows. Everything that must not be forgeable or
replayable lives on the server (the admins row), not only in the cookie:

- step_up_used_at: once a confirmation is used, an older copy of the session
  cookie can't use it again;
- step_up_failures / step_up_locked_until: 5 wrong attempts lock the check
  for 15 minutes;
- face_reset_until: accounts whose saved face can't be checked may confirm
  with their password only after an operator allows it on the server
  (`flask --app app allow-face-reset EMAIL`), and only to re-enroll a face.
"""

import math
import time
from datetime import datetime, timezone

from flask import session
from sqlalchemy import or_, update

from fipconnect.extensions import db
from fipconnect.models import Admin
from fipconnect.services import face

WINDOW = 300  # seconds a confirmation lasts
MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60
RESET_ALLOWANCE_SECONDS = 60 * 60

FACE = "face"
PASSWORD = "password"

_AT = "step_up_at"
_METHOD = "step_up_method"


def now():
    return time.time()


def _as_time(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc)


def _seconds(moment):
    return None if moment is None else moment.timestamp()


def has_usable_face(admin):
    return bool(admin and admin.face_embedding and admin.face_model == face.FACE_MODEL)


# ---- attempts and lockout ------------------------------------------------

def locked_seconds(admin):
    until = _seconds(admin.step_up_locked_until)
    return 0 if until is None else max(0, int(until - now() + 0.999))


def record_failure(admin):
    admin.step_up_failures = (admin.step_up_failures or 0) + 1
    if admin.step_up_failures >= MAX_FAILURES:
        admin.step_up_failures = 0
        admin.step_up_locked_until = _as_time(now() + LOCK_SECONDS)
    db.session.commit()


# ---- password fallback permission -------------------------------------------

def reset_allowed(admin):
    until = _seconds(admin.face_reset_until)
    return until is not None and until > now()


def allow_face_reset(admin, seconds=RESET_ALLOWANCE_SECONDS):
    admin.face_reset_until = _as_time(now() + seconds)
    db.session.commit()


# ---- the confirmation itself ----------------------------------------------------

def mark_verified(admin, method):
    admin.step_up_failures = 0
    admin.step_up_locked_until = None
    db.session.commit()
    session[_AT] = now()
    session[_METHOD] = method


def seconds_left(admin):
    verified_at = session.get(_AT)
    if not isinstance(verified_at, (int, float)) or admin is None:
        return 0
    used_at = _seconds(admin.step_up_used_at)
    # (1 ms tolerance: the database keeps microseconds, the cookie keeps a float)
    if used_at is not None and used_at >= verified_at - 0.001:
        return 0  # already used (possibly from an older copy of this cookie)
    elapsed = now() - verified_at
    return 0 if elapsed >= WINDOW else math.ceil(WINDOW - elapsed)


def method():
    return session.get(_METHOD)


def is_fresh(admin, require_face=False):
    if seconds_left(admin) <= 0:
        return False
    return method() == FACE if require_face else True


def consume(admin_id):
    """Use up the current confirmation inside the caller's transaction.
    Returns False if it was already used (e.g. a replayed cookie or a request
    racing this one); the caller must then roll back and refuse."""
    verified_at = session.get(_AT)
    if not isinstance(verified_at, (int, float)):
        return False
    stamp = _as_time(verified_at)
    result = db.session.execute(
        update(Admin)
        .where(Admin.id == admin_id)
        .where(or_(Admin.step_up_used_at.is_(None), Admin.step_up_used_at < stamp))
        .values(step_up_used_at=stamp)
    )
    return result.rowcount == 1


def forget():
    session.pop(_AT, None)
    session.pop(_METHOD, None)
