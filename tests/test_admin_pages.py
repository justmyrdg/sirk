import re
from datetime import date, timedelta
from unittest.mock import patch

from fipconnect.extensions import db
from fipconnect.models import Block, Booking, Inquiry, Service, SiteSettings
from fipconnect.services import face, inquiries
from tests.base import DatabaseTestCase

ADMIN = "http://admin.localhost"


def csrf_from(html):
    match = re.search(r'name="csrf-token" content="([^"]+)"', html)
    return match.group(1) if match else ""


def future(days=30):
    return (date.today() + timedelta(days=days)).isoformat()


class AdminWorkspaceTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.make_app(ALLOW_SETUP=True)
        self.client = self.app.test_client()
        csrf = self.get("/api/admin/bootstrap").get_json()["csrfToken"]
        with patch.object(face, "extract_face_embedding", return_value=[0.1] * 128):
            created = self.client.post(
                "/api/setup-admin", base_url=ADMIN, headers={"X-CSRF-Token": csrf},
                json={"email": "admin@example.com", "password": "test-password-123",
                      "faceImage": "ZmFrZS1pbWFnZQ=="},
            )
        self.assertEqual(created.status_code, 200)

    # -- helpers --------------------------------------------------------------
    def get(self, path, **kwargs):
        return self.client.get(path, base_url=ADMIN, **kwargs)

    def html(self, path):
        response = self.get(path)
        return response, response.get_data(as_text=True)

    def post(self, path, data=None, token=True):
        data = dict(data or {})
        if token:
            data["csrf_token"] = csrf_from(self.get("/inquiries").get_data(as_text=True))
        return self.client.post(path, base_url=ADMIN, data=data)

    def inquiry(self, event_date=None, name="Garden Wedding"):
        with self.app.app_context():
            return inquiries.submit_inquiry({
                "name": "Test Client", "email": "test@example.com", "phone": "09171234567",
                "eventName": name, "eventDate": event_date or future(), "termsAccepted": True,
            }).id

    def approve(self, inquiry_id, revenue="12000"):
        return self.post(f"/inquiries/{inquiry_id}", {"status": "Approved", "expectedRevenue": revenue})

    # -- tests ------------------------------------------------------------------
    def test_dashboard_shows_stats_and_recent(self):
        self.inquiry(name="Garden Wedding")
        self.inquiry(name="Company Launch", event_date=future(60))
        response, html = self.html("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Total inquiries", html)
        self.assertIn("Garden Wedding", html)
        self.assertIn("Company Launch", html)
        self.assertNotIn("JSON file", html)

    def test_inquiries_list_links_to_review(self):
        inquiry_id = self.inquiry()
        html = self.html("/inquiries")[1]
        self.assertIn(f'href="/inquiries/{inquiry_id}"', html)
        review = self.html(f"/inquiries/{inquiry_id}")[1]
        self.assertIn("test@example.com", review)
        self.assertIn('name="status"', review)

    def test_review_approve_creates_booking(self):
        day = future(25)
        inquiry_id = self.inquiry(day)
        response = self.approve(inquiry_id)
        self.assertEqual(response.status_code, 303)
        with self.app.app_context():
            self.assertEqual(Booking.query.one().status, "Confirmed")
        html = self.html(f"/schedule?month={day[:7]}")[1]
        self.assertIn("Garden Wedding", html)
        self.assertIn("₱12,000", html)
        self.assertIn("Inquiry updated.", self.html("/inquiries")[1] + html)

    def test_second_approval_same_date_shows_409_message(self):
        day = future(40)
        first, second = self.inquiry(day), self.inquiry(day)
        self.approve(first)
        response = self.approve(second)
        self.assertEqual(response.status_code, 409)
        self.assertIn("This date is already booked or unavailable.", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Booking.query.count(), 1)
            self.assertEqual(db.session.get(Inquiry, second).status, "Submitted")

    def test_block_and_unblock(self):
        booked = future(15)
        self.approve(self.inquiry(booked))
        refused = self.post("/blocks", {"date": booked, "reason": "x"})
        self.assertEqual(refused.status_code, 409)
        self.assertIn("That date is already unavailable.", refused.get_data(as_text=True))
        self.assertEqual(self.post("/blocks", {"date": future(16), "reason": "Team off"}).status_code, 303)
        with self.app.app_context():
            block_id = Block.query.one().id
        self.assertEqual(self.post(f"/blocks/{block_id}/delete").status_code, 303)
        again = self.post(f"/blocks/{block_id}/delete")
        self.assertEqual(again.status_code, 404)
        self.assertIn("Date block not found.", again.get_data(as_text=True))

    def test_complete_booking_page(self):
        self.approve(self.inquiry())
        with self.app.app_context():
            booking_id = Booking.query.one().id
        self.assertEqual(self.get(f"/bookings/{booking_id}/complete").status_code, 200)
        bad = self.post(f"/bookings/{booking_id}/complete", {"actualRevenue": "inf"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("Actual revenue must be a valid non-negative amount.", bad.get_data(as_text=True))
        self.assertEqual(self.post(f"/bookings/{booking_id}/complete", {"actualRevenue": "15000"}).status_code, 303)
        self.assertIn("₱15,000", self.html("/analytics")[1])

    def test_services_crud(self):
        self.assertEqual(self.post("/services", {"name": "Photo Booth", "description": "Fun"}).status_code, 303)
        self.assertIn("Photo Booth", self.html("/services")[1])
        with self.app.app_context():
            service_id = Service.query.filter_by(name="Photo Booth").one().id
        self.assertEqual(self.post(f"/services/{service_id}/edit", {"name": "Photo Corner", "description": "Fun"}).status_code, 303)
        self.assertIn("Photo Corner", self.client.get("/").get_data(as_text=True))
        self.assertEqual(self.post(f"/services/{service_id}/toggle").status_code, 303)
        self.assertNotIn("Photo Corner", self.client.get("/").get_data(as_text=True))
        self.assertEqual(self.post(f"/services/{service_id}/delete").status_code, 303)
        self.assertNotIn("Photo Corner", self.html("/services")[1])

    def test_service_edit_error_keeps_typed_values(self):
        response = self.post("/services/svc-wedding/edit", {"name": "Typed Name", "description": "x" * 241})
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Provide a service name and description within the allowed lengths.", html)
        self.assertIn('value="Typed Name"', html)

    def test_landing_update_shows_on_client_home(self):
        response = self.post("/landing", {"organizer": "New Org", "headline": "Fresh, headline", "intro": "Hello"})
        self.assertEqual(response.status_code, 303)
        self.assertIn("New Org", self.client.get("/").get_data(as_text=True))

    def test_schedule_bad_month_falls_back(self):
        self.assertEqual(self.get("/schedule?month=2027-13").status_code, 200)

    def test_unknown_ids_render_404(self):
        for path in ("/inquiries/nope", "/services/nope/edit", "/bookings/nope/complete"):
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertIn("text/html", response.content_type)

    def test_workspace_pages_redirect_when_signed_out(self):
        signed_out = self.app.test_client()
        for path in ("/", "/inquiries", "/schedule"):
            with self.subTest(path=path):
                response = signed_out.get(path, base_url=ADMIN)
                self.assertIn(response.status_code, (302, 303))
                self.assertTrue(response.headers["Location"].endswith("/login"))

    def test_workspace_404_on_client_host(self):
        for path in ("/inquiries", "/schedule", "/services", "/analytics", "/landing", "/admins/new"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_post_without_csrf_rejected(self):
        response = self.post("/landing", {"organizer": "X", "headline": "Y", "intro": "Z"}, token=False)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Your session expired. Refresh the page and try again.", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.get(SiteSettings, 1).organizer, "Flare Infinity Productions")

    def test_delete_buttons_ask_for_confirmation(self):
        html = self.html("/services")[1]
        self.assertIn("data-confirm=", html)

    def test_old_json_workspace_api_is_gone(self):
        token = self.get("/api/admin/bootstrap").get_json()["csrfToken"]
        for method, path in (("get", "/api/admin/data"), ("put", "/api/landing"), ("post", "/api/blocks")):
            with self.subTest(path=path):
                response = getattr(self.client, method)(path, base_url=ADMIN, headers={"X-CSRF-Token": token}, json={})
                self.assertIn(response.status_code, (404, 405))

    def test_concurrent_change_shows_html_409(self):
        from sqlalchemy.orm.exc import StaleDataError

        token = csrf_from(self.get("/landing").get_data(as_text=True))
        with patch("fipconnect.services.catalog.db.session.commit", side_effect=StaleDataError("gone")):
            response = self.client.post(
                "/landing", base_url=ADMIN,
                data={"organizer": "O", "headline": "H", "intro": "I", "csrf_token": token},
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn("text/html", response.content_type)
        self.assertIn("That record was changed by someone else. Refresh and try again.",
                      response.get_data(as_text=True))

    def test_schedule_extreme_months_fall_back(self):
        for value in ("9999-12", "0001-01"):
            with self.subTest(value=value):
                self.assertEqual(self.get(f"/schedule?month={value}").status_code, 200)
