"""Admin accounts: counting, password sign-in, and creating accounts."""

from flask import current_app
from sqlalchemy import func, select
from werkzeug.security import check_password_hash, generate_password_hash

from fipconnect.extensions import db
from fipconnect.models import Admin
from fipconnect.services import face


def admin_count():
    return db.session.scalar(select(func.count()).select_from(Admin))


def authenticate(email, password):
    if not isinstance(email, str) or not isinstance(password, str):
        return None
    admin = db.session.scalar(select(Admin).where(Admin.email == email.strip().lower()))
    if admin and check_password_hash(admin.password_hash, password):
        return admin
    return None


def email_taken(email):
    return db.session.scalar(select(Admin.id).where(Admin.email == email)) is not None


def new_admin(email, password, embedding):
    return Admin(
        email=email,
        password_hash=generate_password_hash(password),
        face_embedding=face.encrypt_face_embedding(current_app.secret_key, embedding),
        face_model=face.FACE_MODEL,
    )
