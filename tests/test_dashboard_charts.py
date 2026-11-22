import json
import re
from datetime import date, timedelta
from unittest.mock import patch

from fipconnect.services import face, inquiries
from tests.base import DatabaseTestCase

ADMIN = "http://admin.localhost"


def chart_json(html, chart_id):
    match = re.search(
        rf'<script type="application/json" id="chart-data-{chart_id}">(.*?)</script>', html, re.S
    )
    return None if match is None else (match.group(1), json.loads(match.group(1)))


class SignedInAdminCase(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        # Chart tests book events for today; the 7-day lead-time rule isn't under test here.
        self.app = self.make_app(ALLOW_SETUP=True, MIN_LEAD_DAYS=0)
        self.client = self.app.test_client()
        csrf = self.client.get("/api/admin/bootstrap", base_url=ADMIN).get_json()["csrfToken"]
        with patch.object(face, "extract_face_embedding", return_value=[0.1] * 128):
            created = self.client.post(
                "/api/setup-admin", base_url=ADMIN, headers={"X-CSRF-Token": csrf},
                json={"email": "admin@example.com", "password": "test-password-123",
                      "faceImage": "ZmFrZS1pbWFnZQ=="},
            )
        self.assertEqual(created.status_code, 200)

    def page(self, path):
        response = self.client.get(path, base_url=ADMIN)
        self.assertEqual(response.status_code, 200, path)
        return response.get_data(as_text=True)

    def add_inquiry(self, event_name="Garden Wedding", event_date=None):
        with self.app.app_context():
            inquiries.submit_inquiry({
                "name": "Test Client", "email": "test@example.com", "phone": "09171234567",
                "eventName": event_name,
                "eventDate": (event_date or date.today() + timedelta(days=30)).isoformat(),
                "termsAccepted": True,
            })


class DashboardChartTests(SignedInAdminCase):
    def test_dashboard_shows_six_kpis(self):
        html = self.page("/")
        for label in ("Total inquiries", "Needs attention", "Upcoming bookings",
                      "Conversion", "Expected revenue", "Completed revenue"):
            with self.subTest(label=label):
                self.assertIn(label, html)

    def test_dashboard_embeds_chart_data(self):
        self.add_inquiry(event_date=date.today())  # inside both the 12-month and 6-month windows
        with self.app.app_context():
            from fipconnect.models import Inquiry

            inquiries.change_status(Inquiry.query.one().id, "Approved", 12000)
        html = self.page("/")
        _, inquiries_data = chart_json(html, "inquiries")
        self.assertEqual(inquiries_data["kind"], "line")
        self.assertEqual(len(inquiries_data["labels"]), 12)
        self.assertEqual(inquiries_data["series"][0]["values"][-1], 1)
        _, revenue = chart_json(html, "revenue")
        self.assertEqual([s["name"] for s in revenue["series"]], ["Booked (expected)", "Completed (actual)"])
        self.assertEqual(sum(revenue["series"][0]["values"]), 12000.0)
        _, pipeline = chart_json(html, "pipeline")
        self.assertEqual(sum(pipeline["series"][0]["values"]), 12000.0)
        self.assertIn("₱12,000", html)
        self.assertIn("vendor/chart.umd.min.js", html)
        self.assertIn("charts.js", html)

    def test_dashboard_with_no_data_renders_empty_states(self):
        html = self.page("/")
        self.assertIn("Forecast available after 6 months of data (0 so far).", html)
        self.assertIn("No inquiries in the last 12 months yet.", html)

    def test_chart_json_is_escaped(self):
        self.add_inquiry(event_name="</script><b>x")
        html = self.page("/")
        raw, parsed = chart_json(html, "inquiries")
        self.assertNotIn("</script><b>", raw)
        self.assertEqual(parsed["kind"], "line")

    def test_chart_scripts_not_on_client_host(self):
        home = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("chart", home.lower().replace("chart-", ""))
        self.assertEqual(self.client.get("/admin-static/vendor/chart.umd.min.js").status_code, 404)
        self.assertEqual(self.client.get("/admin-static/charts.js").status_code, 404)


class ChartBuildTests(SignedInAdminCase):
    def test_projection_history_ends_at_last_complete_month(self):
        from fipconnect.controllers.workspace_pages import dashboard_charts
        from fipconnect.services import metrics

        today = date(2027, 1, 10)
        labels = metrics.month_keys(today)
        per_month = {"labels": labels, "counts": list(range(12))}
        revenue = {"labels": labels, "expected": [0.0] * 12, "actual": [0.0] * 12}
        outlook = {
            "pipeline": {"labels": labels[:6], "expected": [0.0] * 6},
            "months_of_history": 8, "min_history": 6,
            "projection": {"labels": ["2027-02", "2027-03", "2027-04"], "basis": ["2026-10", "2026-11", "2026-12"],
                           "estimate": 9.0, "low": 8, "high": 10},
        }
        data = dashboard_charts(per_month, revenue, outlook)["projection"]["data"]
        self.assertEqual(data["labels"][:6], labels[-7:-1])
        self.assertNotIn("2027-01", data["labels"])
        self.assertEqual(data["series"][0]["values"][:6], list(range(5, 11)))

    def test_hidden_table_shows_dash_for_missing_values(self):
        from flask import render_template_string

        with self.app.test_request_context():
            text = render_template_string(
                '{% from "partials/chart.html" import value_text %}'
                '[{{ value_text(None, "count") }}][{{ value_text(2.0, "count") }}][{{ value_text(None, "peso") }}]'
            )
        self.assertEqual(text, "[—][2][—]")
