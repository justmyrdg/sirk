import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fipconnect.services import metrics


def inquiry(created, status="Submitted", event_date=None):
    return SimpleNamespace(
        created_at=datetime.fromisoformat(created).replace(tzinfo=timezone.utc),
        status=status,
        event_date=date.fromisoformat(event_date or created[:10]),
        id=f"inq-{created}-{status}",
        event_name="Event",
    )


def booking(day, status="Confirmed", expected="0", actual=None, inquiry_id=None):
    return SimpleNamespace(
        date=date.fromisoformat(day),
        status=status,
        expected_revenue=Decimal(expected),
        actual_revenue=None if actual is None else Decimal(actual),
        inquiry_id=inquiry_id,
    )


class MetricsTests(unittest.TestCase):
    def test_month_series_crosses_year(self):
        self.assertEqual(
            metrics.month_keys(date(2027, 1, 15), 3), ["2026-11", "2026-12", "2027-01"]
        )

    def test_inquiries_per_month_fills_empty_months(self):
        rows = [inquiry("2026-11-02"), inquiry("2026-11-20"), inquiry("2027-01-05")]
        series = metrics.inquiries_per_month(rows, date(2027, 1, 15))
        self.assertEqual(len(series["labels"]), 12)
        self.assertEqual(series["labels"][-1], "2027-01")
        counts = dict(zip(series["labels"], series["counts"]))
        self.assertEqual((counts["2026-11"], counts["2026-12"], counts["2027-01"]), (2, 0, 1))

    def test_kpis_count_only_confirmed_upcoming(self):
        today = date(2027, 1, 15)
        bookings = [
            booking("2027-02-01", "Confirmed", expected="10000"),
            booking("2027-01-01", "Confirmed", expected="7000"),
            booking("2027-03-01", "Cancelled", expected="9000"),
            booking("2026-12-01", "Completed", expected="4000", actual="5000"),
        ]
        rows = [inquiry("2027-01-03", "Submitted"), inquiry("2026-12-03", "Approved")]
        result = metrics.kpis(rows, bookings, today)
        self.assertEqual(result["upcoming"], 1)
        self.assertEqual(result["expected_upcoming"], Decimal("10000"))
        self.assertEqual(result["actual_completed"], Decimal("5000"))
        self.assertEqual(result["pending"], 1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["this_month"], 1)
        self.assertEqual(result["conversion"], 100)

    def test_revenue_per_month_splits_expected_and_actual(self):
        bookings = [
            booking("2027-01-20", "Confirmed", expected="12000"),
            booking("2026-12-05", "Completed", expected="4000", actual="5000.50"),
            booking("2026-12-06", "Cancelled", expected="9999"),
        ]
        series = metrics.revenue_per_month(bookings, date(2027, 1, 15))
        by_month = {label: (e, a) for label, e, a in zip(series["labels"], series["expected"], series["actual"])}
        self.assertEqual(by_month["2027-01"], (12000.0, 0.0))
        self.assertEqual(by_month["2026-12"], (4000.0, 5000.5))
        self.assertTrue(all(isinstance(value, float) for value in series["expected"] + series["actual"]))

    def test_projection_threshold_excludes_current_month(self):
        rows = [inquiry("2026-07-03")]
        ready = metrics.forecast(rows, [], date(2027, 1, 10))
        self.assertEqual(ready["months_of_history"], 6)
        self.assertIsNotNone(ready["projection"])
        early = metrics.forecast(rows, [], date(2026, 12, 31))
        self.assertEqual(early["months_of_history"], 5)
        self.assertIsNone(early["projection"])

    def test_projection_average_and_range(self):
        rows = [inquiry("2026-06-10")]
        rows += [inquiry(f"2026-10-0{i}") for i in range(1, 3)]  # 2
        rows += [inquiry(f"2026-11-0{i}") for i in range(1, 5)]  # 4
        rows += [inquiry(f"2026-12-0{i}") for i in range(1, 7)]  # 6
        projection = metrics.forecast(rows, [], date(2027, 1, 10))["projection"]
        self.assertEqual(projection["estimate"], 4.0)
        self.assertEqual((projection["low"], projection["high"]), (2, 6))
        self.assertEqual(projection["labels"], ["2027-02", "2027-03", "2027-04"])

    def test_pipeline_next_six_months(self):
        bookings = [
            booking("2027-03-10", "Confirmed", expected="8000"),
            booking("2027-09-10", "Confirmed", expected="1000"),
            booking("2027-03-11", "Cancelled", expected="5000"),
        ]
        pipeline = metrics.forecast([], bookings, date(2027, 1, 10))["pipeline"]
        self.assertEqual(pipeline["labels"], ["2027-01", "2027-02", "2027-03", "2027-04", "2027-05", "2027-06"])
        self.assertEqual(pipeline["expected"][2], 8000.0)
        self.assertEqual(sum(pipeline["expected"]), 8000.0)

    def test_empty_data(self):
        today = date(2027, 1, 10)
        result = metrics.kpis([], [], today)
        self.assertEqual((result["total"], result["upcoming"], result["conversion"]), (0, 0, 0))
        self.assertEqual(result["expected_upcoming"], Decimal("0"))
        self.assertEqual(sum(metrics.inquiries_per_month([], today)["counts"]), 0)
        self.assertEqual(sum(metrics.revenue_per_month([], today)["expected"]), 0)
        empty_forecast = metrics.forecast([], [], today)
        self.assertEqual(empty_forecast["months_of_history"], 0)
        self.assertIsNone(empty_forecast["projection"])

    def test_months_follow_philippine_time(self):
        # 23:30 UTC on Nov 30 is 07:30 on Dec 1 in the Philippines.
        rows = [SimpleNamespace(created_at=datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc),
                                status="Submitted", id="x", event_name="E", event_date=date(2027, 1, 1))]
        series = metrics.inquiries_per_month(rows, date(2026, 12, 5))
        counts = dict(zip(series["labels"], series["counts"]))
        self.assertEqual((counts["2026-11"], counts["2026-12"]), (0, 1))
        self.assertEqual(metrics.kpis(rows, [], date(2026, 12, 5))["this_month"], 1)

    def test_local_today_uses_philippine_date(self):
        late_utc = datetime(2026, 11, 30, 18, 0, tzinfo=timezone.utc)  # 02:00 Dec 1 in PH
        self.assertEqual(metrics.local_today(late_utc), date(2026, 12, 1))
