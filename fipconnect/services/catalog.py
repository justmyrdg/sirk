"""Services offered and the public landing page text."""

import secrets

from sqlalchemy import delete, func, select

from fipconnect.extensions import db
from fipconnect.models import Service, SiteSettings
from fipconnect.services.errors import reject

SERVICE_LIMITS = "Provide a service name and description within the allowed lengths."
LANDING_LIMITS = {"organizer": 120, "headline": 160, "intro": 500}


def _service_text(name, description):
    name = str(name or "").strip()
    description = str(description or "").strip()
    if not name or not description or len(name) > 100 or len(description) > 240:
        reject(SERVICE_LIMITS)
    return name, description


def _get(service_id):
    service = db.session.get(Service, service_id)
    if service is None:
        reject("Service not found.", 404)
    return service


def add_service(name, description):
    name, description = _service_text(name, description)
    last_position = db.session.scalar(select(func.max(Service.position)))
    service = Service(
        id="svc-" + secrets.token_urlsafe(10),
        name=name,
        description=description,
        active=True,
        position=0 if last_position is None else last_position + 1,
    )
    db.session.add(service)
    db.session.commit()
    return service


def edit_service(service_id, name, description):
    service = _get(service_id)
    service.name, service.description = _service_text(name, description)
    db.session.commit()
    return service


def set_service_active(service_id, active):
    if not isinstance(active, bool):
        reject("Service visibility must be true or false.")
    service = _get(service_id)
    service.active = active
    db.session.commit()
    return service


def delete_service(service_id):
    deleted = db.session.execute(delete(Service).where(Service.id == service_id)).rowcount
    db.session.commit()
    if not deleted:
        reject("Service not found.", 404)


def update_landing(organizer, headline, intro):
    values = {
        "organizer": str(organizer or "").strip(),
        "headline": str(headline or "").strip(),
        "intro": str(intro or "").strip(),
    }
    if any(not values[field] or len(values[field]) > limit for field, limit in LANDING_LIMITS.items()):
        reject("Complete each landing page field within its allowed length.")
    settings = db.session.get(SiteSettings, 1)
    for field, value in values.items():
        setattr(settings, field, value)
    db.session.commit()
    return settings
