import re
from datetime import date, timedelta
from decimal import Decimal

from fipconnect.extensions import db
from fipconnect.models import Booking, Inquiry, Service
from fipconnect.views import month_ph
from tests.base import DatabaseTestCase

ADMIN = {"base_url": "http://admin.localhost"}
BANNED = ("/api/admin", "register-admin", "setup-admin", "/api/login", "login", "face", "Admin")


def csrf_from(html):
    match = re.search(r'name="csrf-token" content="([^"]+)"', html)
    return match.group(1) if match else ""


def future(days=30):
    return (date.today() + timedelta(days=days)).isoformat()


class ClientPageTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.make_app()
        self.client = self.app.test_client()

    def form(self, **overrides):
        data = {
            "name": "Test Client",
            "email": "test@example.com",
            "phone": "09171234567",
            "eventName": "Garden Wedding",
            "eventDate": future(),
            "terms": "on",
        }
        data.update(overrides)
        return data

    def post_inquiry(self, with_token=True, **overrides):
        data = self.form(**overrides)
        if with_token:
            data["csrf_token"] = csrf_from(self.client.get("/inquire").get_data(as_text=True))
        return self.client.post("/inquire", data=data)

    def text(self, path, **kwargs):
        response = self.client.get(path, **kwargs)
        return response, response.get_data(as_text=True)

    def test_home_lists_active_services_and_landing(self):
        response, html = self.text("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Wedding Production", html)
        self.assertIn("Your moments", html)
        with self.app.app_context():
            db.session.get(Service, "svc-social").active = False
            db.session.commit()
        self.assertNotIn("Social Celebrations", self.text("/")[1])

    def test_availability_marks_booked_and_links_free_days(self):
        booked = date.today() + timedelta(days=20)
        with self.app.app_context():
            db.session.add(Booking(id="b1", client_name="c", event_name="e", date=booked,
                                   status="Confirmed", expected_revenue=Decimal("0")))
            db.session.commit()
        response, html = self.text(f"/availability?month={booked.strftime('%Y-%m')}")
        self.assertEqual(response.status_code, 200)
        cell = re.search(rf'<[^>]*data-date="{booked.isoformat()}"[^>]*>', html).group(0)
        self.assertIn("is-unavailable", cell)
        free = booked + timedelta(days=1) if (booked + timedelta(days=1)).month == booked.month else booked - timedelta(days=1)
        if free >= date.today():
            self.assertIn(f'href="/inquire?date={free.isoformat()}"', html)

    def test_availability_bad_month_falls_back(self):
        response, html = self.text("/availability?month=abc")
        self.assertEqual(response.status_code, 200)
        self.assertIn(month_ph(date.today()), html)

    def test_inquire_form_prefills_date(self):
        html = self.text("/inquire?date=2027-11-16")[1]
        self.assertRegex(html, r'name="eventDate"[^>]*value="2027-11-16"')

    def test_inquiry_success_redirects_to_thanks_with_code(self):
        response = self.post_inquiry()
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/inquire/thanks"))
        html = self.text("/inquire/thanks")[1]
        with self.app.app_context():
            reference = Inquiry.query.one().reference
        self.assertIn(reference, html)
        again = self.client.get("/inquire/thanks")
        self.assertIn(again.status_code, (302, 303))

    def test_thanks_without_submission_redirects(self):
        response = self.client.get("/inquire/thanks")
        self.assertIn(response.status_code, (302, 303))
        self.assertTrue(response.headers["Location"].endswith("/inquire"))

    def test_inquiry_error_keeps_typed_values(self):
        response = self.post_inquiry(eventDate=(date.today() - timedelta(days=1)).isoformat())
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Please choose today or a future event date.", html)
        self.assertIn('value="Test Client"', html)
        self.assertIn('value="Garden Wedding"', html)

    def test_inquiry_without_csrf_rerenders_with_values(self):
        self.client.get("/inquire")
        response = self.post_inquiry(with_token=False)
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Your session expired. Refresh the page and try again.", html)
        self.assertIn('value="Test Client"', html)
        with self.app.app_context():
            self.assertEqual(Inquiry.query.count(), 0)

    def test_non_finite_budget_is_rejected(self):
        response = self.post_inquiry(budget="NaN")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Budget must be a non-negative valid amount.", response.get_data(as_text=True))

    def test_status_lookup(self):
        self.post_inquiry()
        with self.app.app_context():
            reference = Inquiry.query.one().reference
        token = csrf_from(self.text("/status")[1])
        response = self.client.post("/status", data={"reference": reference.lower(), "csrf_token": token})
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Garden Wedding", html)
        self.assertIn("Submitted", html)
        self.assertNotIn("test@example.com", html)
        missing = self.client.post("/status", data={"reference": "FIP-NOPE", "csrf_token": token})
        self.assertEqual(missing.status_code, 404)
        self.assertIn("No inquiry was found for that code.", missing.get_data(as_text=True))

    def test_client_pages_ship_no_admin_code(self):
        paths = ["/", "/availability", "/inquire", "/status", "/static/js/site.js"]
        for path in paths:
            response = self.client.get(path)
            body = response.get_data(as_text=True)
            response.close()
            self.assertEqual(response.status_code, 200, path)
            for banned in BANNED:
                with self.subTest(path=path, banned=banned):
                    self.assertNotIn(banned, body)

    def test_client_routes_404_on_admin_host(self):
        for path in ("/availability", "/inquire", "/status", "/inquire/thanks"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, **ADMIN).status_code, 404)

    def test_home_redirects_old_hash_links(self):
        self.assertIn("#inquiry", self.text("/static/js/site.js")[1])

    def test_availability_extreme_months_fall_back(self):
        for value in ("9999-12", "0001-01"):
            with self.subTest(value=value):
                response = self.client.get(f"/availability?month={value}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(month_ph(date.today()), response.get_data(as_text=True))

    def test_calendar_marks_too_soon_days(self):
        from fipconnect.services.metrics import local_today

        today = local_today()
        soon, first_open = today + timedelta(days=3), today + timedelta(days=7)
        html = self.text(f"/availability?month={soon.strftime('%Y-%m')}")[1]
        cell = re.search(rf'<[^>]*data-date="{soon.isoformat()}"[^>]*>.*?</(span|a)>', html, re.S).group(0)
        self.assertIn("is-too-soon", cell)
        self.assertIn("Too soon", cell)
        self.assertNotIn("href", cell)
        self.assertIn("Too soon (less than 7 days away)", html)
        html = self.text(f"/availability?month={first_open.strftime('%Y-%m')}")[1]
        self.assertIn(f'href="/inquire?date={first_open.isoformat()}"', html)

    def test_lead_time_is_highlighted_to_clients(self):
        from fipconnect.services.metrics import local_today
        from fipconnect.views import date_long

        first_open = local_today() + timedelta(days=7)
        expected = f"The earliest date you can request is {date_long(first_open)}."
        for path in ("/availability", "/inquire"):
            with self.subTest(path=path):
                html = self.text(path)[1]
                self.assertIn("Book at least 7 days ahead.", html)
                self.assertIn(expected, html)
        self.assertRegex(self.text("/inquire")[1], rf'name="eventDate"[^>]*min="{first_open.isoformat()}"')

    def test_too_soon_date_is_refused_by_form(self):
        from fipconnect.services.metrics import local_today

        response = self.post_inquiry(eventDate=(local_today() + timedelta(days=2)).isoformat())
        self.assertEqual(response.status_code, 400)
        self.assertIn("Please choose a date at least 7 days from today.", response.get_data(as_text=True))
