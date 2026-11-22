import unittest
from datetime import date
from decimal import Decimal

from fipconnect.services.calendar import calendar_weeks, month_from_param, shift_month
from fipconnect.views import date_ph, month_ph, peso
from tests.base import DatabaseTestCase

DOWN = "postgresql+psycopg://postgres:x@127.0.0.1:1/none"
DOWN_OPTIONS = {"connect_args": {"connect_timeout": 1}}
MESSAGE = "The database is unavailable. Please try again shortly."


class FilterTests(unittest.TestCase):
    def test_filters(self):
        self.assertEqual(date_ph(date(2027, 11, 16)), "Nov 16, 2027")
        self.assertEqual(date_ph("2027-11-16"), "Nov 16, 2027")
        self.assertEqual(month_ph(date(2027, 11, 1)), "November 2027")
        self.assertEqual(peso(12000), "₱12,000")
        self.assertEqual(peso(Decimal("90000.50")), "₱90,000.50")
        self.assertEqual(peso(0), "₱0")
        self.assertEqual(peso(None), "—")


class CalendarTests(unittest.TestCase):
    def test_month_from_param_falls_back(self):
        today = date(2026, 11, 22)
        for value in ("abc", "2027-13", "", None, "2027-00", "9999-12", "0001-01", "1-1", "99999-01"):
            with self.subTest(value=value):
                self.assertEqual(month_from_param(value, today), date(2026, 11, 1))
        self.assertEqual(month_from_param("2027-02", today), date(2027, 2, 1))

    def test_calendar_weeks_shape(self):
        weeks = calendar_weeks(date(2026, 2, 1))
        self.assertTrue(all(len(week) == 7 for week in weeks))
        self.assertEqual(weeks[0][0], date(2026, 2, 1))  # Feb 1, 2026 is a Sunday
        self.assertEqual(sum(day is not None for week in weeks for day in week), 28)
        november = calendar_weeks(date(2026, 11, 1))
        self.assertEqual(november[0][0], date(2026, 11, 1))
        march = calendar_weeks(date(2027, 3, 1))
        self.assertEqual(march[0][:1], [None])  # Mar 1, 2027 is a Monday
        self.assertEqual(march[0][1], date(2027, 3, 1))

    def test_shift_month(self):
        self.assertEqual(shift_month(date(2026, 12, 1), 1), date(2027, 1, 1))
        self.assertEqual(shift_month(date(2027, 1, 1), -1), date(2026, 12, 1))


class ErrorPageTests(DatabaseTestCase):
    def test_html_error_page_when_db_down(self):
        app = self.make_app(SQLALCHEMY_DATABASE_URI=DOWN, SQLALCHEMY_ENGINE_OPTIONS=DOWN_OPTIONS)
        response = app.test_client().get("/availability")
        self.assertEqual(response.status_code, 500)
        self.assertIn("text/html", response.content_type)
        self.assertIn(MESSAGE, response.get_data(as_text=True))

    def test_json_error_kept_under_api(self):
        app = self.make_app(SQLALCHEMY_DATABASE_URI=DOWN, SQLALCHEMY_ENGINE_OPTIONS=DOWN_OPTIONS)
        response = app.test_client().get("/api/admin/bootstrap", base_url="http://admin.localhost")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {"error": MESSAGE})

    def test_unknown_page_renders_html_404(self):
        response = self.make_app().test_client().get("/no-such-page")
        self.assertEqual(response.status_code, 404)
        self.assertIn("text/html", response.content_type)
        self.assertIn("Page not found", response.get_data(as_text=True))

    def test_csrf_protect_marks_unsafe_page_posts(self):
        app = self.make_app()

        @app.post("/_csrf_probe")
        def probe():
            from flask import g

            return {"failed": bool(g.get("csrf_failed"))}

        @app.get("/_csrf_token")
        def token_probe():
            from fipconnect.services.security import csrf_token

            return {"token": csrf_token()}

        client = app.test_client()
        self.assertTrue(client.post("/_csrf_probe", data={}).get_json()["failed"])
        token = client.get("/_csrf_token").get_json()["token"]
        self.assertFalse(
            client.post("/_csrf_probe", data={"csrf_token": token}).get_json()["failed"]
        )
