import json
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from fipconnect.cli import ImportRefused, import_json
from fipconnect.extensions import db
from fipconnect.models import Admin, Block, Booking, Inquiry, Service, SiteSettings
from fipconnect.services import face
from tests.base import DatabaseTestCase

SECRET = "test-only-secret"


def inquiry_record(record_id, reference, status="Submitted", event_date="2027-11-16"):
    return {
        "id": record_id,
        "reference": reference,
        "name": "Test Client",
        "email": "client@example.com",
        "phone": "09171234567",
        "eventName": "Wedding",
        "eventDate": event_date,
        "venue": "Manila",
        "guests": 100,
        "budget": 90000.0,
        "service": "Wedding Production",
        "notes": "",
        "status": status,
        "createdAt": "2026-11-20T08:00:00+00:00",
        "termsAccepted": True,
    }


def export_file(**overrides):
    data = {
        "admins": [
            {
                "username": "admin@example.com",
                "email": "admin@example.com",
                "passwordHash": generate_password_hash("pw-123456"),
                "faceEmbedding": face.encrypt_face_embedding(SECRET, [0.1] * 128),
                "faceModel": face.FACE_MODEL,
            }
        ],
        "inquiries": [
            inquiry_record("inq-one", "FIP-AAAAAAAA", status="Approved"),
            inquiry_record("inq-two", "FIP-BBBBBBBB", event_date="2027-12-01"),
        ],
        "bookings": [
            {
                "id": "booking-one",
                "inquiryId": "inq-one",
                "clientName": "Test Client",
                "eventName": "Wedding",
                "date": "2027-11-16",
                "venue": "Manila",
                "status": "Confirmed",
                "expectedRevenue": 12000,
                "actualRevenue": None,
            }
        ],
        "blocks": [{"id": "block-one", "date": "2027-10-01", "reason": "Team off"}],
        "services": [
            {"id": "svc-a", "name": "A", "description": "First", "active": True},
            {"id": "svc-b", "name": "B", "description": "Second", "active": False},
        ],
        "landing": {"organizer": "Org", "headline": "Head", "intro": "Intro"},
    }
    data.update(overrides)
    return data


class ImportTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = self.make_app(SECRET_KEY=SECRET)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write(self, data):
        path = Path(self.temp_dir.name) / "fipconnect.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def run_import(self, data):
        with self.app.app_context():
            return import_json(self.write(data))

    def test_import_copies_records_with_original_ids(self):
        counts = self.run_import(export_file())
        self.assertEqual(
            counts, {"admins": 1, "inquiries": 2, "bookings": 1, "blocks": 1, "services": 2}
        )
        with self.app.app_context():
            self.assertEqual(db.session.get(Inquiry, "inq-one").reference, "FIP-AAAAAAAA")
            self.assertEqual(db.session.get(Booking, "booking-one").inquiry_id, "inq-one")
            self.assertEqual(db.session.get(Block, "block-one").reason, "Team off")
            self.assertEqual(
                [s.id for s in Service.query.order_by(Service.position)], ["svc-a", "svc-b"]
            )
            self.assertEqual(
                db.session.get(SiteSettings, 1).to_dict(),
                {"organizer": "Org", "headline": "Head", "intro": "Intro"},
            )

    def test_imported_admin_can_sign_in_with_password_and_face(self):
        self.run_import(export_file())
        client = self.app.test_client()
        base = {"base_url": "http://admin.localhost"}

        def page_token(path):
            html = client.get(path, **base).get_data(as_text=True)
            return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

        signed_in = client.post(
            "/login", data={"email": "admin@example.com", "password": "pw-123456",
                            "csrf_token": page_token("/login")}, **base,
        )
        self.assertEqual(signed_in.status_code, 303)
        self.assertEqual(client.get("/admins/new", **base).status_code, 200)
        client.post("/logout", data={"csrf_token": page_token("/admins/new")}, **base)
        csrf = client.get("/api/admin/bootstrap", **base).get_json()["csrfToken"]
        with patch.object(face, "match_face_embedding", return_value=0) as match:
            face_login = client.post(
                "/api/login/face", headers={"X-CSRF-Token": csrf},
                json={"faceImage": "ZmFrZS1pbWFnZQ=="}, **base,
            )
        self.assertEqual(face_login.status_code, 200)
        self.assertEqual(match.call_args.args[1], [[0.1] * 128])

    def test_import_accepts_legacy_single_admin_key(self):
        data = export_file()
        data["admin"] = data.pop("admins")[0]
        self.assertEqual(self.run_import(data)["admins"], 1)

    def test_import_refuses_when_database_has_data(self):
        self.run_import(export_file())
        with self.assertRaises(ImportRefused) as refused:
            self.run_import(export_file())
        self.assertIn("already has data", str(refused.exception))

    def test_import_aborts_whole_file_on_bad_record(self):
        data = export_file(inquiries=[inquiry_record("inq-bad", "FIP-CCCCCCCC", status="Bogus")], bookings=[])
        with self.assertRaises(ImportRefused) as refused:
            self.run_import(data)
        self.assertIn("inq-bad", str(refused.exception))
        with self.app.app_context():
            self.assertEqual(Admin.query.count(), 0)
            self.assertEqual(Service.query.count(), 3)

    def test_cli_reports_counts(self):
        path = self.write(export_file())
        result = self.app.test_cli_runner().invoke(args=["import-json", str(path)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Imported 1 admins, 2 inquiries, 1 bookings, 1 blocks, 2 services", result.output)
