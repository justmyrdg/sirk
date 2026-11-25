import os
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fipconnect.config import load_env_file
from fipconnect.extensions import db
from fipconnect.models import Admin
from fipconnect.services import face, inquiries
from tests.base import DatabaseTestCase


ADMIN_BASE_URL = "http://admin.localhost"


class AdminClient:
    """Sends every request to the admin host."""

    def __init__(self, client):
        self.client = client

    def _call(self, method, path, **kwargs):
        kwargs.setdefault("base_url", ADMIN_BASE_URL)
        return getattr(self.client, method)(path, **kwargs)

    def get(self, path, **kwargs):
        return self._call("get", path, **kwargs)

    def post(self, path, **kwargs):
        return self._call("post", path, **kwargs)

    def put(self, path, **kwargs):
        return self._call("put", path, **kwargs)

    def delete(self, path, **kwargs):
        return self._call("delete", path, **kwargs)


class FIPConnectAppTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = self.make_app(ALLOW_SETUP=True)
        self.client = self.app.test_client()
        self.admin = AdminClient(self.client)
        self.csrf = self.admin_csrf()

    def page_token(self):
        html = self.admin.get("/login").get_data(as_text=True)
        if 'name="csrf-token"' not in html:
            html = self.admin.get("/admins/new").get_data(as_text=True)
        match = re.search(r'name="csrf-token" content="([^"]+)"', html)
        return match.group(1) if match else self.admin_csrf()

    def form_logout(self):
        response = self.admin.post("/logout", data={"csrf_token": self.page_token()})
        self.csrf = self.admin_csrf()
        return response

    def form_login(self, email, password, face_matches=True):
        """Password, then (for accounts with a usable face) the face step.
        Returns the password response; self.face_verify is the face check's mock."""
        response = self.admin.post(
            "/login", data={"email": email, "password": password, "csrf_token": self.page_token()}
        )
        self.csrf = self.admin_csrf()
        self.face_verify = None
        if response.headers.get("Location", "").endswith("/login/face"):
            with patch.object(face, "verify_face_embedding", return_value=face_matches) as verify:
                self.face_response = self.admin.post(
                    "/api/login/face", headers=self.headers(), json={"faceImage": "ZmFrZS1pbWFnZQ=="}
                )
            self.face_verify = verify
            self.csrf = self.admin_csrf()
        return response

    def confirm_its_me(self):
        """Pass the 'confirm it's you' face check before adding admins / re-enrolling."""
        with patch.object(face, "verify_face_embedding", return_value=True):
            response = self.admin.post(
                "/api/admin/verify-face", headers=self.headers(),
                json={"faceImage": "ZmFrZS1pbWFnZQ=="},
            )
        self.assertEqual(response.status_code, 200)

    def confirm_with_password(self, password="test-password-123"):
        response = self.admin.post(
            "/api/admin/verify-password", headers=self.headers(), json={"password": password}
        )
        self.assertEqual(response.status_code, 200)

    def admin_csrf(self):
        return self.admin.get("/api/admin/bootstrap").get_json()["csrfToken"]

    def tearDown(self):
        self.temp_dir.cleanup()

    def headers(self):
        return {"X-CSRF-Token": self.csrf}

    def submit_inquiry(self, event_date=None):
        """Create an inquiry the way the client form does; returns its reference."""
        with self.app.app_context():
            return inquiries.submit_inquiry(
                {
                    "name": "Test Client",
                    "email": "test@example.com",
                    "phone": "09171234567",
                    "eventName": "Test Event",
                    "eventDate": event_date or (date.today() + timedelta(days=30)).isoformat(),
                    "termsAccepted": True,
                }
            ).reference

    def setup_admin(self):
        with patch.object(
            face, "extract_face_embedding", return_value=[0.1] * 128
        ):
            response = self.admin.post(
                "/api/setup-admin",
                headers=self.headers(),
                json={
                    "email": "admin@example.com",
                    "password": "test-password-123",
                    "faceImage": "ZmFrZS1pbWFnZQ==",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.csrf = response.get_json()["csrfToken"]

    def test_admin_can_reenroll_face_after_password_login(self):
        self.setup_admin()
        with self.app.app_context():
            Admin.query.one().face_model = "Facenet512"
            db.session.commit()
        self.form_logout()

        signed_in = self.form_login("admin@example.com", "test-password-123")
        self.assertEqual(signed_in.status_code, 303)
        # The saved face is the old model: an operator allows a reset, then the password confirms.
        self.assertEqual(
            self.app.test_cli_runner().invoke(args=["allow-face-reset", "admin@example.com"]).exit_code, 0
        )
        self.confirm_with_password()
        new_embedding = [0.25] * 128
        with patch.object(
            face, "extract_face_embedding", return_value=new_embedding
        ) as extract:
            reenrolled = self.admin.post(
                "/api/admin/face",
                headers=self.headers(),
                json={"faceImage": "ZmFrZS1pbWFnZQ=="},
            )
        self.assertEqual(reenrolled.status_code, 200)
        extract.assert_called_once()
        with self.app.app_context():
            stored = Admin.query.one()
            self.assertEqual(stored.face_model, face.FACE_MODEL)
            self.assertTrue(stored.face_embedding.startswith("gAAAA"))
            self.assertNotIn("0.25", stored.face_embedding)

    def test_face_reenrollment_requires_admin_session(self):
        response = self.admin.post(
            "/api/admin/face",
            headers=self.headers(),
            json={"faceImage": "ZmFrZS1pbWFnZQ=="},
        )
        self.assertEqual(response.status_code, 401)

    def test_signed_in_admin_creates_additional_admins_with_unique_face_templates(self):
        self.setup_admin()
        self.confirm_its_me()
        additional_embedding = [0.2] * 128
        with patch.object(
            face, "extract_face_embedding", return_value=additional_embedding
        ) as extract:
            created = self.admin.post(
                "/api/register-admin",
                headers=self.headers(),
                json={
                    "email": "second@example.com",
                    "password": "second-password-123",
                    "faceImage": "ZmFrZS1pbWFnZQ==",
                },
            )
        self.assertEqual(created.status_code, 200)
        extract.assert_called_once()
        with self.app.app_context():
            stored = Admin.query.order_by(Admin.id).all()
            self.assertEqual(
                [admin.email for admin in stored],
                ["admin@example.com", "second@example.com"],
            )
            self.assertTrue(stored[1].face_embedding.startswith("gAAAA"))

        self.confirm_its_me()
        duplicate = self.admin.post(
            "/api/register-admin",
            headers=self.headers(),
            json={
                "email": "SECOND@example.com",
                "password": "another-password-123",
                "faceImage": "ZmFrZS1pbWFnZQ==",
            },
        )
        self.assertEqual(duplicate.status_code, 409)

        self.form_logout()
        signed_in = self.form_login("SECOND@example.com", "second-password-123")
        self.assertEqual(signed_in.status_code, 303)
        self.assertIn("Good day, second@example.com.", self.admin.get("/").get_data(as_text=True))
        # The face step checks only the second admin's own template.
        self.assertEqual(self.face_response.status_code, 200)
        self.face_verify.assert_called_once()
        self.assertEqual(self.face_verify.call_args.args[1], [0.2] * 128)

    def test_admin_setup_requires_face_capture(self):
        response = self.admin.post(
            "/api/setup-admin",
            headers=self.headers(),
            json={"email": "admin@example.com", "password": "test-password-123"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.admin.get("/api/admin/bootstrap").get_json()["adminConfigured"])

    def test_admin_setup_rejects_invalid_camera_image(self):
        response = self.admin.post(
            "/api/setup-admin",
            headers=self.headers(),
            json={
                "email": "admin@example.com",
                "password": "test-password-123",
                "faceImage": "not-an-image",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.admin.get("/api/admin/bootstrap").get_json()["adminConfigured"])

    def test_admin_setup_requires_valid_email(self):
        with patch.object(face, "extract_face_embedding") as extract:
            response = self.admin.post(
                "/api/setup-admin",
                headers=self.headers(),
                json={
                    "email": "not-an-email",
                    "password": "test-password-123",
                    "faceImage": "ZmFrZS1pbWFnZQ==",
                },
            )
        self.assertEqual(response.status_code, 400)
        extract.assert_not_called()

    def test_setup_is_unavailable_after_first_account(self):
        self.setup_admin()
        with patch.object(face, "extract_face_embedding") as extract:
            response = self.admin.post(
                "/api/setup-admin",
                headers=self.headers(),
                json={
                    "email": "another-admin@example.com",
                    "password": "another-password-123",
                    "faceImage": "ZmFrZS1pbWFnZQ==",
                },
            )
        self.assertEqual(response.status_code, 409)
        extract.assert_not_called()

    def test_flask_template_and_static_asset_routes(self):
        for asset in (
            "/static/css/styles.css",
            "/static/js/site.js",
            "/static/images/logo_flare.png",
        ):
            with self.subTest(asset=asset):
                response = self.client.get(asset)
                self.assertEqual(response.status_code, 200)
                response.close()

    def test_admin_script_is_only_served_on_admin_host(self):
        self.assertEqual(self.client.get("/admin-static/admin.js").status_code, 404)
        response = self.admin.get("/admin-static/admin.js")
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_loopback_ip_redirects_to_localhost(self):
        response = self.client.get(
            "/availability",
            base_url="http://127.0.0.1:5000",
        )
        self.assertEqual(response.status_code, 308)
        self.assertEqual(
            response.headers["Location"],
            "http://localhost:5000/availability",
        )
        redirected = self.client.get(response.headers["Location"])
        self.assertEqual(redirected.request.host, "localhost:5000")
        self.assertEqual(redirected.status_code, 200)

    def test_admin_routes_require_login_and_admin_mutations_require_csrf(self):
        forbidden = self.admin.get("/admins/new")
        self.assertIn(forbidden.status_code, (302, 303))
        missing_csrf = self.admin.post(
            "/api/setup-admin",
            json={
                "email": "admin@example.com",
                "password": "test-password-123",
            },
        )
        self.assertEqual(missing_csrf.status_code, 400)

    def test_face_alone_does_not_sign_in(self):
        self.setup_admin()
        self.form_logout()
        with patch.object(face, "verify_face_embedding", return_value=True) as verify:
            denied = self.admin.post(
                "/api/login/face",
                headers=self.headers(),
                json={"faceImage": "ZmFrZS1pbWFnZQ=="},
            )
        verify.assert_not_called()
        self.assertEqual(denied.status_code, 401)
        self.assertIn(self.admin.get("/admins/new").status_code, (302, 303))

    def test_unmatched_face_does_not_create_admin_session(self):
        self.setup_admin()
        self.form_logout()
        self.form_login("admin@example.com", "test-password-123", face_matches=False)
        self.assertEqual(self.face_response.status_code, 401)
        self.assertIn(self.admin.get("/admins/new").status_code, (302, 303))

    def test_admin_can_sign_in_with_email_and_password(self):
        self.setup_admin()
        with self.app.app_context():
            stored = Admin.query.one()
            self.assertEqual(stored.email, "admin@example.com")
            self.assertTrue(stored.face_embedding.startswith("gAAAA"))
            self.assertNotIn("0.1", stored.face_embedding)
        self.form_logout()
        signed_in = self.form_login("ADMIN@example.com", "test-password-123")
        self.assertEqual(signed_in.status_code, 303)
        self.assertEqual(self.admin.get("/admins/new").status_code, 200)

    def test_admin_apis_return_404_on_client_host(self):
        for method, path in [
            ("get", "/api/admin/bootstrap"),
            ("post", "/api/setup-admin"), ("post", "/api/register-admin"),
            ("post", "/api/login/face"), ("post", "/api/admin/face"),
        ]:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(
                    path, headers=self.headers(), json={}
                )
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.get_json(), {"error": "Not found."})

    def test_admin_host_match_ignores_case_and_port(self):
        response = self.client.get(
            "/api/admin/bootstrap", base_url="http://Admin.Localhost:5000"
        )
        self.assertEqual(response.status_code, 200)

    def test_admin_session_is_not_usable_from_client_host(self):
        self.setup_admin()
        self.assertEqual(self.admin.get("/admins/new").status_code, 200)
        self.assertEqual(self.client.get("/admins/new").status_code, 404)

    def test_register_admin_requires_signed_in_admin(self):
        account = {
            "email": "x@example.com",
            "password": "password-123",
            "faceImage": "ZmFrZS1pbWFnZQ==",
        }
        with patch.object(face, "extract_face_embedding") as extract:
            response = self.admin.post(
                "/api/register-admin",
                headers={"X-CSRF-Token": self.admin_csrf()},
                json=account,
            )
        self.assertEqual(response.status_code, 401)
        extract.assert_not_called()
        self.setup_admin()
        self.form_logout()
        response = self.admin.post(
            "/api/register-admin",
            headers={"X-CSRF-Token": self.admin_csrf()},
            json=account,
        )
        self.assertEqual(response.status_code, 401)

    def test_admin_host_is_configurable(self):
        app = self.make_app(SECRET_KEY="k", ADMIN_HOST="admin.example.com")
        client = app.test_client()
        self.assertEqual(
            client.get(
                "/api/admin/bootstrap", base_url="http://admin.example.com"
            ).status_code,
            200,
        )
        self.assertEqual(
            client.get(
                "/api/admin/bootstrap", base_url="http://admin.localhost"
            ).status_code,
            404,
        )

    def test_default_admin_host_only_answers_local_requests(self):
        remote = {"REMOTE_ADDR": "203.0.113.5"}
        self.assertEqual(
            self.admin.get(
                "/api/admin/bootstrap", environ_overrides=remote
            ).status_code,
            404,
        )
        self.assertEqual(
            self.admin.get("/", environ_overrides=remote).get_data(as_text=True).count("admin.js"),
            0,
        )

    def test_configured_admin_host_answers_remote_requests(self):
        app = self.make_app(SECRET_KEY="k", ADMIN_HOST="admin.example.com")
        response = app.test_client().get(
            "/api/admin/bootstrap",
            base_url="http://admin.example.com",
            environ_overrides={"REMOTE_ADDR": "203.0.113.5"},
        )
        self.assertEqual(response.status_code, 200)

    def test_env_file_loader_sets_missing_variables_only(self):
        env_file = Path(self.temp_dir.name) / ".env"
        env_file.write_text(
            "# comment\n"
            "\n"
            "FIP_TEST_PLAIN=plain value\n"
            "FIP_TEST_QUOTED=\"quoted value\"\n"
            "FIP_TEST_KEEP=from-file\n"
            "not a valid line\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"FIP_TEST_KEEP": "from-shell"}, clear=False):
            load_env_file(env_file)
            self.assertEqual(os.environ["FIP_TEST_PLAIN"], "plain value")
            self.assertEqual(os.environ["FIP_TEST_QUOTED"], "quoted value")
            self.assertEqual(os.environ["FIP_TEST_KEEP"], "from-shell")
            os.environ.pop("FIP_TEST_PLAIN")
            os.environ.pop("FIP_TEST_QUOTED")

    def test_env_file_loader_ignores_missing_file(self):
        load_env_file(Path(self.temp_dir.name) / "missing.env")

    def setup_disabled_admin(self):
        app = self.make_app(SECRET_KEY="k", ALLOW_SETUP=False)
        admin = AdminClient(app.test_client())
        csrf = admin.get("/api/admin/bootstrap").get_json()["csrfToken"]
        return admin, csrf

    def test_first_time_setup_is_refused_when_switch_is_off(self):
        admin, csrf = self.setup_disabled_admin()
        with patch.object(face, "extract_face_embedding") as extract:
            response = admin.post(
                "/api/setup-admin",
                headers={"X-CSRF-Token": csrf},
                json={
                    "email": "admin@example.com",
                    "password": "test-password-123",
                    "faceImage": "ZmFrZS1pbWFnZQ==",
                },
            )
        self.assertEqual(response.status_code, 403)
        self.assertIn("FIP_ALLOW_SETUP", response.get_json()["error"])
        extract.assert_not_called()
        self.assertFalse(
            admin.get("/api/admin/bootstrap").get_json()["adminConfigured"]
        )

    def test_admin_bootstrap_reports_setup_switch(self):
        admin, _ = self.setup_disabled_admin()
        self.assertFalse(admin.get("/api/admin/bootstrap").get_json()["setupAllowed"])
        self.assertTrue(self.admin.get("/api/admin/bootstrap").get_json()["setupAllowed"])

    def test_setup_switch_reads_env_values(self):
        for value, expected in [("true", True), ("1", True), ("YES", True),
                                ("false", False), ("", False), ("nope", False)]:
            with self.subTest(value=value):
                with patch.dict(os.environ, {"FIP_ALLOW_SETUP": value}):
                    app = self.make_app(SECRET_KEY="k")
                self.assertIs(app.config["ALLOW_SETUP"], expected)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FIP_ALLOW_SETUP", None)
            app = self.make_app(SECRET_KEY="k")
        self.assertFalse(app.config["ALLOW_SETUP"])

    def test_database_unavailable_returns_json_500(self):
        app = self.make_app(
            SQLALCHEMY_DATABASE_URI="postgresql+psycopg://postgres:x@127.0.0.1:1/none",
            SQLALCHEMY_ENGINE_OPTIONS={"connect_args": {"connect_timeout": 1}},
        )
        response = app.test_client().get("/api/admin/bootstrap", base_url="http://admin.localhost")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {"error": "The database is unavailable. Please try again shortly."},
        )

    def test_session_survives_across_requests_with_admin_id(self):
        self.setup_admin()
        self.assertIn("Good day, admin@example.com.", self.admin.get("/").get_data(as_text=True))

    def test_test_suite_refuses_to_run_against_the_real_database(self):
        from tests import base

        same = {"TEST_DATABASE_URL": "postgresql+psycopg://u:p@h/real",
                "DATABASE_URL": "postgresql+psycopg://u:p@h/real"}
        with patch.dict(os.environ, same), patch.object(base, "load_env_file"):
            with self.assertRaises(RuntimeError) as refused:
                base.test_database_uri()
        self.assertIn("same database", str(refused.exception))

    def test_registering_same_email_concurrently_returns_409_json(self):
        self.setup_admin()
        self.confirm_its_me()
        with patch("fipconnect.controllers.auth.email_taken", return_value=False),                 patch.object(face, "extract_face_embedding", return_value=[0.3] * 128):
            response = self.admin.post(
                "/api/register-admin", headers=self.headers(),
                json={"email": "admin@example.com", "password": "another-pw-123",
                      "faceImage": "ZmFrZS1pbWFnZQ=="},
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["error"],
            "An administrator account with this email already exists.",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
