from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from fipconnect.config import database_url
from fipconnect.extensions import db
from fipconnect.models import Admin, Block, Booking, Inquiry, Service, SiteSettings
from tests.base import DatabaseTestCase


def make_inquiry(**overrides):
    values = dict(
        id="inq-1",
        reference="FIP-AAAAAAAA",
        name="Test Client",
        email="client@example.com",
        phone="09171234567",
        event_name="Wedding",
        event_date=date(2027, 11, 16),
        venue="Manila",
        guests=780,
        budget=Decimal("90000.50"),
        service="Wedding Production",
        notes="",
        status="Submitted",
        terms_accepted=True,
        created_at=datetime(2026, 11, 21, 8, 0, tzinfo=timezone.utc),
    )
    values.update(overrides)
    return Inquiry(**values)


def make_booking(**overrides):
    values = dict(
        id="booking-1",
        inquiry_id=None,
        client_name="Test Client",
        event_name="Wedding",
        date=date(2027, 11, 16),
        venue="",
        status="Confirmed",
        expected_revenue=Decimal("12000"),
        actual_revenue=None,
    )
    values.update(overrides)
    return Booking(**values)


class ModelTests(DatabaseTestCase):
    def test_inquiry_to_dict_matches_api_shape(self):
        with self.db_app.app_context():
            db.session.add(make_inquiry())
            db.session.commit()
            data = db.session.get(Inquiry, "inq-1").to_dict()
        self.assertEqual(
            set(data),
            {"id", "reference", "name", "email", "phone", "eventName", "eventDate",
             "venue", "guests", "budget", "service", "notes", "status", "createdAt",
             "termsAccepted"},
        )
        self.assertIs(type(data["budget"]), float)
        self.assertEqual(data["budget"], 90000.5)
        self.assertEqual(data["eventDate"], "2027-11-16")
        self.assertTrue(data["createdAt"].endswith("+00:00"))
        self.assertEqual(data["guests"], 780)

    def test_booking_to_dict_matches_api_shape(self):
        with self.db_app.app_context():
            db.session.add(make_booking())
            db.session.commit()
            data = db.session.get(Booking, "booking-1").to_dict()
        self.assertEqual(
            set(data),
            {"id", "inquiryId", "clientName", "eventName", "date", "venue",
             "status", "expectedRevenue", "actualRevenue"},
        )
        self.assertIs(type(data["expectedRevenue"]), float)
        self.assertIsNone(data["actualRevenue"])
        self.assertEqual(data["date"], "2027-11-16")

    def test_service_block_landing_admin_to_dict(self):
        with self.db_app.app_context():
            db.session.add(Block(id="block-1", date=date(2027, 1, 2), reason="Team off"))
            db.session.add(Admin(email="a@example.com", password_hash="x"))
            db.session.commit()
            service = Service.query.order_by(Service.position).first().to_dict()
            block = db.session.get(Block, "block-1").to_dict()
            landing = db.session.get(SiteSettings, 1).to_dict()
            admin = Admin.query.one().to_dict()
        self.assertEqual(set(service), {"id", "name", "description", "active"})
        self.assertEqual(block, {"id": "block-1", "date": "2027-01-02", "reason": "Team off"})
        self.assertEqual(set(landing), {"organizer", "headline", "intro"})
        self.assertEqual(admin, {"username": "a@example.com"})

    def test_two_confirmed_bookings_on_one_date_are_rejected(self):
        with self.db_app.app_context():
            db.session.add(make_booking())
            db.session.add(make_booking(id="booking-cancelled", status="Cancelled"))
            db.session.commit()
            db.session.add(make_booking(id="booking-2"))
            with self.assertRaises(IntegrityError):
                db.session.commit()

    def test_block_dates_are_unique(self):
        with self.db_app.app_context():
            db.session.add(Block(id="block-1", date=date(2027, 1, 2), reason=""))
            db.session.add(Block(id="block-2", date=date(2027, 1, 2), reason=""))
            with self.assertRaises(IntegrityError):
                db.session.commit()

    def test_invalid_inquiry_status_is_rejected(self):
        with self.db_app.app_context():
            db.session.add(make_inquiry(status="Bogus"))
            with self.assertRaises(IntegrityError):
                db.session.commit()

    def test_seed_defaults_creates_three_services_and_landing(self):
        with self.db_app.app_context():
            ids = [service.id for service in Service.query.order_by(Service.position)]
            landing = db.session.get(SiteSettings, 1)
        self.assertEqual(ids, ["svc-wedding", "svc-corporate", "svc-social"])
        self.assertEqual(landing.organizer, "Flare Infinity Productions")

    def test_database_url_normalizes_render_scheme(self):
        self.assertEqual(database_url("postgres://u:p@h/d"), "postgresql+psycopg://u:p@h/d")
        self.assertEqual(database_url("postgresql://u:p@h/d"), "postgresql+psycopg://u:p@h/d")
        self.assertEqual(
            database_url("postgresql+psycopg://u:p@h/d"), "postgresql+psycopg://u:p@h/d"
        )
        with self.assertRaises(RuntimeError):
            database_url("")
        with self.assertRaises(RuntimeError):
            database_url(None)
