from datetime import date

from fipconnect.models import Inquiry
from fipconnect.services import inquiries
from tests.test_dashboard_charts import SignedInAdminCase, chart_json


class AnalyticsChartTests(SignedInAdminCase):
    def test_analytics_embeds_charts(self):
        self.add_inquiry(event_name="Garden Wedding", event_date=date.today())
        with self.app.app_context():
            inquiries.change_status(Inquiry.query.one().id, "Approved", 9000)
        html = self.page("/analytics")
        _, months = chart_json(html, "event-months")
        self.assertEqual(months["kind"], "bar")
        self.assertEqual(sum(months["series"][0]["values"]), 1)
        _, types = chart_json(html, "event-types")
        self.assertEqual(types["kind"], "hbar")
        self.assertEqual(types["labels"], ["Garden Wedding"])
        _, bookings = chart_json(html, "booking-months")
        self.assertEqual(sum(bookings["series"][0]["values"]), 1)
        self.assertIn("Revenue data", html)
        self.assertIn("vendor/chart.umd.min.js", html)

    def test_analytics_with_no_data(self):
        html = self.page("/analytics")
        for message in ("Inquiry trends will appear after clients submit inquiries.",
                        "Event-type patterns will appear after inquiries are submitted.",
                        "Booking seasonality will appear when events are confirmed."):
            with self.subTest(message=message):
                self.assertIn(message, html)

    def test_event_type_names_are_escaped_in_chart_json(self):
        self.add_inquiry(event_name="</script><b>x")
        raw, parsed = chart_json(self.page("/analytics"), "event-types")
        self.assertNotIn("</script><b>", raw)
        self.assertEqual(parsed["labels"], ["</script><b>x"])
