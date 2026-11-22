from datetime import date, timedelta
from decimal import Decimal

from werkzeug.security import generate_password_hash

from fipconnect.extensions import db
from fipconnect.models import Admin, Block, Booking, Inquiry
from fipconnect.services import accounts, catalog, inquiries, metrics, schedule
from fipconnect.services.errors import ValidationError
from tests.base import DatabaseTestCase


def future(days=30):
    return (date.today() + timedelta(days=days)).isoformat()


def inquiry_data(**overrides):
    data = {
        "name": "Test Client",
        "email": "test@example.com",
        "phone": "09171234567",
        "eventName": "Test Event",
        "eventDate": future(),
        "venue": "",
        "guests": "",
        "budget": "",
        "service": "",
        "notes": "",
        "termsAccepted": True,
    }
    data.update(overrides)
    return data


class DomainTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.context = self.db_app.app_context()
        self.context.push()

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def assert_rejected(self, call, message, status):
        with self.assertRaises(ValidationError) as caught:
            call()
        self.assertEqual((caught.exception.message, caught.exception.status), (message, status))

    def test_submit_inquiry_creates_reference_and_accepts_form_strings(self):
        inquiry = inquiries.submit_inquiry(inquiry_data(guests="100", budget="90000.50"))
        self.assertRegex(inquiry.reference, r"^FIP-[A-Z2-9]{8}$")
        self.assertEqual(float(db.session.get(Inquiry, inquiry.id).budget), 90000.5)
        self.assertEqual(inquiry.guests, 100)

    def test_submit_inquiry_rules_keep_messages(self):
        taken = future(50)
        db.session.add(Block(id="block-taken", date=date.fromisoformat(taken), reason=""))
        db.session.commit()
        cases = [
            (inquiry_data(eventDate=(date.today() - timedelta(days=1)).isoformat()),
             "Please choose today or a future event date.", 400),
            (inquiry_data(email="not-an-email"), "Please enter a valid email address.", 400),
            (inquiry_data(budget="NaN"), "Budget must be a non-negative valid amount.", 400),
            (inquiry_data(termsAccepted=False),
             "Please agree to the inquiry terms before submitting.", 400),
            (inquiry_data(name=""),
             "Please provide your name, email, contact number, event type, and date.", 400),
            (inquiry_data(eventDate=taken, termsAccepted=False),
             "That date is no longer available. Please choose another date.", 409),
        ]
        for data, message, status in cases:
            with self.subTest(message=message):
                self.assert_rejected(lambda: inquiries.submit_inquiry(data), message, status)
        self.assertEqual(Inquiry.query.count(), 0)

    def test_find_by_reference_is_case_insensitive(self):
        inquiry = inquiries.submit_inquiry(inquiry_data())
        self.assertEqual(inquiries.find_by_reference(f"  {inquiry.reference.lower()} ").id, inquiry.id)
        self.assertIsNone(inquiries.find_by_reference("FIP-NOPE"))

    def test_change_status_second_approval_same_date_refused(self):
        day = future(40)
        first = inquiries.submit_inquiry(inquiry_data(eventDate=day))
        second = inquiries.submit_inquiry(inquiry_data(eventDate=day))
        inquiries.change_status(first.id, "Approved", 12000)
        self.assert_rejected(
            lambda: inquiries.change_status(second.id, "Approved", 12000),
            "This date is already booked or unavailable.", 409,
        )
        self.assertEqual(Booking.query.count(), 1)
        self.assertEqual(db.session.get(Inquiry, second.id).status, "Submitted")

    def test_change_status_rules(self):
        inquiry = inquiries.submit_inquiry(inquiry_data())
        self.assert_rejected(lambda: inquiries.change_status(inquiry.id, "Bogus", 0),
                             "Choose a valid inquiry status.", 400)
        self.assert_rejected(lambda: inquiries.change_status("nope", "Approved", 0),
                             "Inquiry not found.", 404)
        self.assert_rejected(lambda: inquiries.change_status(inquiry.id, "Approved", "NaN"),
                             "Expected revenue must be a valid non-negative amount.", 400)

    def test_block_date_on_booked_day_refused(self):
        inquiry = inquiries.submit_inquiry(inquiry_data())
        inquiries.change_status(inquiry.id, "Approved", 0)
        self.assert_rejected(lambda: schedule.block_date(inquiry.event_date.isoformat(), "x"),
                             "That date is already unavailable.", 409)
        self.assertEqual(Block.query.count(), 0)
        self.assert_rejected(lambda: schedule.block_date("2000-01-01", ""),
                             "Choose today or a future date to block.", 400)

    def test_unblock_twice_raises_404(self):
        block = schedule.block_date(future(9), "Team off")
        schedule.unblock(block.id)
        self.assert_rejected(lambda: schedule.unblock(block.id), "Date block not found.", 404)

    def test_complete_booking_rules(self):
        inquiry = inquiries.submit_inquiry(inquiry_data())
        inquiries.change_status(inquiry.id, "Approved", 0)
        booking = Booking.query.one()
        self.assert_rejected(lambda: schedule.complete_booking(booking.id, "abc"),
                             "Actual revenue must be a valid number.", 400)
        self.assert_rejected(lambda: schedule.complete_booking(booking.id, "inf"),
                             "Actual revenue must be a valid non-negative amount.", 400)
        schedule.complete_booking(booking.id, "15000")
        self.assertEqual(db.session.get(Booking, booking.id).actual_revenue, Decimal("15000.00"))
        self.assert_rejected(lambda: schedule.complete_booking(booking.id, "1"),
                             "Only confirmed bookings can be completed.", 409)

    def test_catalog_rules(self):
        limits = "Provide a service name and description within the allowed lengths."
        self.assert_rejected(lambda: catalog.add_service("", "desc"), limits, 400)
        self.assert_rejected(lambda: catalog.edit_service("nope", "a", "b"), "Service not found.", 404)
        self.assert_rejected(lambda: catalog.delete_service("nope"), "Service not found.", 404)
        self.assert_rejected(lambda: catalog.update_landing("", "h", "i"),
                             "Complete each landing page field within its allowed length.", 400)
        service = catalog.add_service("New", "Desc")
        self.assertFalse(catalog.set_service_active(service.id, False).active)
        self.assertEqual(catalog.edit_service(service.id, "Renamed", "D2").name, "Renamed")
        catalog.delete_service(service.id)

    def test_authenticate(self):
        db.session.add(Admin(email="admin@example.com", password_hash=generate_password_hash("pw-123456")))
        db.session.commit()
        self.assertEqual(accounts.authenticate("ADMIN@example.com", "pw-123456").email, "admin@example.com")
        self.assertIsNone(accounts.authenticate("admin@example.com", "wrong"))
        self.assertIsNone(accounts.authenticate("nobody@example.com", "pw-123456"))
        self.assertEqual(accounts.admin_count(), 1)
        self.assertTrue(accounts.email_taken("admin@example.com"))

    def test_lead_time_boundary(self):
        lead = "Please choose a date at least 7 days from today."
        today = metrics.local_today()
        for days in (0, 1, 6):
            with self.subTest(days=days):
                self.assert_rejected(
                    lambda: inquiries.submit_inquiry(inquiry_data(eventDate=(today + timedelta(days=days)).isoformat())),
                    lead, 400,
                )
        self.assert_rejected(
            lambda: inquiries.submit_inquiry(inquiry_data(eventDate=(today - timedelta(days=1)).isoformat())),
            "Please choose today or a future event date.", 400,
        )
        inquiries.submit_inquiry(inquiry_data(eventDate=(today + timedelta(days=7)).isoformat()))
        self.assertEqual(Inquiry.query.count(), 1)

    def test_lead_time_setting_is_respected(self):
        self.db_app.config["MIN_LEAD_DAYS"] = 14
        today = metrics.local_today()
        self.assert_rejected(
            lambda: inquiries.submit_inquiry(inquiry_data(eventDate=(today + timedelta(days=10)).isoformat())),
            "Please choose a date at least 14 days from today.", 400,
        )
        self.assertEqual(inquiries.earliest_bookable(today), today + timedelta(days=14))

    def test_admin_approval_not_limited_by_lead_time(self):
        self.db_app.config["MIN_LEAD_DAYS"] = 0
        inquiry = inquiries.submit_inquiry(inquiry_data(eventDate=(metrics.local_today() + timedelta(days=2)).isoformat()))
        self.db_app.config["MIN_LEAD_DAYS"] = 7
        inquiries.change_status(inquiry.id, "Approved", 1000)
        self.assertEqual(Booking.query.count(), 1)
        schedule.block_date((metrics.local_today() + timedelta(days=3)).isoformat(), "Team off")
