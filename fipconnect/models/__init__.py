from fipconnect.models._types import BOOKING_STATUSES, PENDING_STATUSES, STATUSES
from fipconnect.models.admin import Admin
from fipconnect.models.block import Block
from fipconnect.models.booking import Booking
from fipconnect.models.defaults import DEFAULT_LANDING, DEFAULT_SERVICES
from fipconnect.models.inquiry import Inquiry
from fipconnect.models.inquiry_update import InquiryUpdate
from fipconnect.models.service import Service
from fipconnect.models.site_settings import SiteSettings


def seed_defaults(session):
    """Add the starting services and landing text to an empty database."""
    for position, service in enumerate(DEFAULT_SERVICES):
        session.add(Service(position=position, **service))
    session.add(SiteSettings(id=1, **DEFAULT_LANDING))


__all__ = [
    "Admin", "Block", "Booking", "Inquiry", "InquiryUpdate", "Service", "SiteSettings",
    "STATUSES", "PENDING_STATUSES", "BOOKING_STATUSES",
    "DEFAULT_LANDING", "DEFAULT_SERVICES", "seed_defaults",
]
