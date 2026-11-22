import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from fipconnect.extensions import db
from fipconnect.models import Block, Booking
from fipconnect.services import face
from fipconnect.services.analytics import analytics
from fipconnect.services.availability import lock_date, unavailable_dates
from tests.base import DatabaseTestCase


class FaceServiceTests(unittest.TestCase):
    def test_legacy_face_service_errors_are_translated_to_english(self):
        self.assertEqual(
            face.translate_face_service_error(
                "Hindi makilala ang mukha. Tumingin sa camera at subukan ulit."
            ),
            "Face not recognized. Look at the camera and try again.",
        )
        self.assertEqual(
            face.translate_face_service_error("An unknown service error."),
            "An unknown service error.",
        )

    def test_face_template_round_trip(self):
        token = face.encrypt_face_embedding("k", [0.1] * 128)
        self.assertTrue(token.startswith("gAAAA"))
        self.assertNotIn("0.1", token)
        self.assertEqual(face.decrypt_face_embedding("k", token), [0.1] * 128)
        with self.assertRaises(RuntimeError):
            face.decrypt_face_embedding("other", token)

    def test_ensure_face_service_reuses_service_started_by_another_worker(self):
        exited_process = MagicMock()
        exited_process.poll.return_value = 1
        with patch.object(face, "FACE_SERVICE_PROCESS", None), \
                patch.object(face, "face_service_ready", side_effect=[False, True]), \
                patch.object(face.shutil, "which", return_value="node"), \
                patch.object(face.subprocess, "Popen", return_value=exited_process):
            face.ensure_face_service("http://127.0.0.1:5018", "t")


class AnalyticsTests(unittest.TestCase):
    def test_analytics_groups_by_event_month_and_counts_conversion(self):
        inquiries = [
            {"id": "a", "status": "Approved", "eventDate": "2027-01-10", "eventName": "Wedding"},
            {"id": "b", "status": "Submitted", "eventDate": "2027-03-10", "eventName": "Birthday"},
        ]
        report = analytics(inquiries, [])
        months = {item["month"]: item["count"] for item in report["inquiryMonths"]}
        self.assertEqual(months, {"2027-01": 1, "2027-03": 1})
        self.assertEqual(report["conversionRate"], 100)


class AvailabilityTests(DatabaseTestCase):
    def test_unavailable_dates_includes_confirmed_bookings_and_blocks_only(self):
        with self.db_app.app_context():
            db.session.add(Booking(id="b1", client_name="c", event_name="e",
                                   date=date(2027, 5, 1), status="Confirmed",
                                   expected_revenue=Decimal("0")))
            db.session.add(Booking(id="b2", client_name="c", event_name="e",
                                   date=date(2027, 5, 2), status="Cancelled",
                                   expected_revenue=Decimal("0")))
            db.session.add(Block(id="k1", date=date(2027, 5, 3), reason=""))
            db.session.commit()
            self.assertEqual(unavailable_dates(), {"2027-05-01", "2027-05-03"})

    def test_lock_date_runs_inside_transaction(self):
        with self.db_app.app_context():
            lock_date(date(2027, 1, 1))
            db.session.commit()
