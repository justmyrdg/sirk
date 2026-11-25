import re
from pathlib import Path
from unittest.mock import patch

from fipconnect.services import face
from tests.base import DatabaseTestCase

ADMIN = "http://admin.localhost"
ROOT = Path(__file__).resolve().parents[1]


def csrf_from(html):
    match = re.search(r'name="csrf-token" content="([^"]+)"', html)
    return match.group(1) if match else ""


class AdminAuthPageTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.make_app(ALLOW_SETUP=True)
        self.client = self.app.test_client()

    def get(self, path, **kwargs):
        return self.client.get(path, base_url=ADMIN, **kwargs)

    def post(self, path, **kwargs):
        return self.client.post(path, base_url=ADMIN, **kwargs)

    def token(self, path="/login"):
        return csrf_from(self.get(path).get_data(as_text=True))

    def create_first_admin(self):
        csrf = self.get("/api/admin/bootstrap").get_json()["csrfToken"]
        with patch.object(face, "extract_face_embedding", return_value=[0.1] * 128):
            response = self.post(
                "/api/setup-admin",
                headers={"X-CSRF-Token": csrf},
                json={"email": "admin@example.com", "password": "test-password-123",
                      "faceImage": "ZmFrZS1pbWFnZQ=="},
            )
        self.assertEqual(response.status_code, 200)
        self.logout()

    def login(self, password="test-password-123", email="admin@example.com", finish=True):
        """Password step; with finish, also the face step (face check mocked to match)."""
        response = self.post("/login", data={"email": email, "password": password,
                                             "csrf_token": self.token()})
        if finish and response.headers.get("Location", "").endswith("/login/face"):
            csrf = self.get("/api/admin/bootstrap").get_json()["csrfToken"]
            with patch.object(face, "verify_face_embedding", return_value=True):
                done = self.post("/api/login/face", headers={"X-CSRF-Token": csrf},
                                 json={"faceImage": "ZmFrZS1pbWFnZQ=="})
            self.assertEqual(done.status_code, 200)
        return response

    def logout(self):
        token = self.token("/admins/new") or self.token()
        return self.post("/logout", data={"csrf_token": token})

    def test_login_page_redirects_to_setup_when_no_admins(self):
        response = self.get("/login")
        self.assertIn(response.status_code, (302, 303))
        self.assertTrue(response.headers["Location"].endswith("/setup"))

    def test_setup_page_and_setup_off_page(self):
        html = self.get("/setup").get_data(as_text=True)
        self.assertIn('data-flow="setup"', html)
        off = self.make_app(ALLOW_SETUP=False).test_client()
        self.assertIn("FIP_ALLOW_SETUP=true", off.get("/setup", base_url=ADMIN).get_data(as_text=True))

    def test_setup_redirects_to_login_once_an_admin_exists(self):
        self.create_first_admin()
        response = self.get("/setup")
        self.assertIn(response.status_code, (302, 303))
        self.assertTrue(response.headers["Location"].endswith("/login"))

    def test_password_login_and_logout_round_trip(self):
        self.create_first_admin()
        response = self.login()
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/login/face"))
        self.assertEqual(self.get("/admins/new").status_code, 200)
        self.assertEqual(self.logout().status_code, 303)
        signed_out = self.get("/admins/new")
        self.assertIn(signed_out.status_code, (302, 303))
        self.assertTrue(signed_out.headers["Location"].endswith("/login"))

    def test_wrong_password_rerenders(self):
        self.create_first_admin()
        response = self.login(password="nope-nope-nope")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Incorrect email or password.", html)
        self.assertIn('value="admin@example.com"', html)

    def test_login_without_csrf_is_refused(self):
        self.create_first_admin()
        self.get("/login")
        response = self.post("/login", data={"email": "admin@example.com", "password": "test-password-123"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Your session expired. Refresh the page and try again.", response.get_data(as_text=True))
        self.assertIn(self.get("/admins/new").status_code, (302, 303))

    def test_admin_pages_404_on_client_host(self):
        for path in ("/login", "/setup", "/admins/new", "/account/face"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_camera_pages_have_flow_and_csrf_meta(self):
        self.assertIn('data-flow="setup"', self.get("/setup").get_data(as_text=True))
        self.create_first_admin()
        self.assertNotIn('data-flow="login"', self.get("/login").get_data(as_text=True))
        self.login(finish=False)
        face_step = self.get("/login/face").get_data(as_text=True)
        self.assertIn('data-flow="login"', face_step)
        self.assertIn('<meta name="csrf-token"', face_step)
        self.login()
        # Both pages start at step 1, "confirm it's you" (see tests/test_step_up.py for step 2).
        for path, flow in (("/admins/new", "verify"), ("/account/face", "verify")):
            html = self.get(path).get_data(as_text=True)
            with self.subTest(path=path):
                self.assertIn(f'data-flow="{flow}"', html)
                self.assertIn('<meta name="csrf-token"', html)

    def test_admin_js_builds_no_html(self):
        script = (ROOT / "admin_static" / "admin.js").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("<div", script)
        self.assertIn("/api/login/face", script)
        self.assertIn("/api/register-admin", script)

    def test_camera_panel_lets_you_choose_a_camera(self):
        html = self.get("/setup").get_data(as_text=True)
        self.assertRegex(html, r'<label for="face-camera-select">Camera</label>')
        self.assertRegex(html, r'<select id="face-camera-select"[^>]*>')
        self.assertRegex(html, r'data-camera-choice[^>]*hidden')  # only shown with 2+ cameras
        script = (ROOT / "admin_static" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("enumerateDevices", script)
        self.assertIn('kind === "videoinput"', script)
        self.assertIn("deviceId: { exact:", script)
        # the remembered choice must never break the page when storage is blocked
        self.assertRegex(script, r"try\s*\{\s*(return\s+)?localStorage\.getItem")
        self.assertRegex(script, r"try\s*\{\s*localStorage\.setItem")

    def test_logout_with_stale_token_still_signs_out(self):
        self.create_first_admin()
        self.login()
        response = self.post("/logout", data={"csrf_token": "stale-token-from-another-tab"})
        self.assertEqual(response.status_code, 303)
        signed_out = self.get("/admins/new")
        self.assertIn(signed_out.status_code, (302, 303))
        self.assertTrue(signed_out.headers["Location"].endswith("/login"))
