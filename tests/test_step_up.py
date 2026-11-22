import re
from pathlib import Path
from unittest.mock import patch

from fipconnect.extensions import db
from fipconnect.models import Admin
from fipconnect.services import face, step_up
from tests.base import DatabaseTestCase

ADMIN = "http://admin.localhost"
PHOTO = "ZmFrZS1pbWFnZQ=="
ROOT = Path(__file__).resolve().parents[1]


class StepUpTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.make_app(ALLOW_SETUP=True)
        self.client = self.app.test_client()
        self.csrf = self.client.get("/api/admin/bootstrap", base_url=ADMIN).get_json()["csrfToken"]
        with patch.object(face, "extract_face_embedding", return_value=[0.1] * 128):
            created = self.api("/api/setup-admin", email="admin@example.com",
                               password="test-password-123", faceImage=PHOTO)
        self.assertEqual(created.status_code, 200)
        self.csrf = created.get_json()["csrfToken"]

    # -- helpers ----------------------------------------------------------------
    def api(self, path, csrf=True, base_url=ADMIN, **body):
        headers = {"X-CSRF-Token": self.csrf} if csrf else {}
        return self.client.post(path, base_url=base_url, headers=headers, json=body)

    def verify(self, result=True):
        with patch.object(face, "verify_face_embedding", return_value=result) as verify:
            response = self.api("/api/admin/verify-face", faceImage=PHOTO)
        return response, verify

    def register(self, email="second@example.com", embedding=None, error=None):
        kwargs = {"side_effect": error} if error else {"return_value": embedding or [0.2] * 128}
        with patch.object(face, "extract_face_embedding", **kwargs) as extract:
            response = self.api("/api/register-admin", email=email,
                                password="second-password-123", faceImage=PHOTO)
        return response, extract

    def page(self, path):
        return self.client.get(path, base_url=ADMIN).get_data(as_text=True)

    # -- rules --------------------------------------------------------------------
    def test_register_admin_requires_fresh_check(self):
        response, extract = self.register()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "Confirm it's you first.")
        extract.assert_not_called()

    def test_verify_face_then_register(self):
        verified, _ = self.verify()
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(verified.get_json(), {"ok": True, "secondsLeft": 300})
        response, _ = self.register()
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(Admin.query.count(), 2)

    def test_verify_face_rejects_mismatch(self):
        response, _ = self.verify(result=False)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "Face not recognized. Please try again.")
        self.assertEqual(self.register()[0].status_code, 403)

    def test_verify_face_compares_only_own_template(self):
        self.verify()
        self.register()  # adds B with [0.2] * 128
        _, verify = self.verify()
        self.assertEqual(verify.call_args.args[1], [0.1] * 128)

    def test_check_expires_after_five_minutes(self):
        with patch.object(step_up, "now", return_value=1000.0):
            self.verify()
        with patch.object(step_up, "now", return_value=1301.0):
            response, _ = self.register()
        self.assertEqual(response.status_code, 403)

    def test_check_is_used_up_by_success(self):
        self.verify()
        self.assertEqual(self.register()[0].status_code, 200)
        self.assertEqual(self.register(email="third@example.com")[0].status_code, 403)

    def test_failed_action_keeps_check(self):
        self.verify()
        failed, _ = self.register(error=ValueError("Could not read the camera capture. Please try again."))
        self.assertEqual(failed.status_code, 400)
        self.assertEqual(self.register()[0].status_code, 200)

    def test_reenroll_requires_fresh_check(self):
        with patch.object(face, "extract_face_embedding", return_value=[0.3] * 128):
            self.assertEqual(self.api("/api/admin/face", faceImage=PHOTO).status_code, 403)
            self.verify()
            self.assertEqual(self.api("/api/admin/face", faceImage=PHOTO).status_code, 200)

    def set_old_model(self):
        with self.app.app_context():
            Admin.query.one().face_model = "Facenet512"
            db.session.commit()

    def test_old_model_account_uses_password(self):
        self.set_old_model()
        blocked, _ = self.verify()
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.get_json()["error"],
                         "Your saved face can't be checked. Confirm with your password.")
        self.allow_face_reset()
        wrong = self.api("/api/admin/verify-password", password="nope-nope")
        self.assertEqual((wrong.status_code, wrong.get_json()["error"]), (401, "Incorrect password."))
        right = self.api("/api/admin/verify-password", password="test-password-123")
        self.assertEqual(right.status_code, 200)
        with patch.object(face, "extract_face_embedding", return_value=[0.3] * 128):
            self.assertEqual(self.api("/api/admin/face", faceImage=PHOTO).status_code, 200)

    def allow_face_reset(self, email="admin@example.com"):
        result = self.app.test_cli_runner().invoke(args=["allow-face-reset", email])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("allowed", result.output)

    def test_password_needs_operator_permission(self):
        self.set_old_model()
        refused = self.api("/api/admin/verify-password", password="test-password-123")
        self.assertEqual(refused.status_code, 403)
        self.assertIn("allow-face-reset", refused.get_json()["error"])
        self.allow_face_reset()
        self.assertEqual(self.api("/api/admin/verify-password", password="test-password-123").status_code, 200)

    def test_password_confirmation_cannot_add_admin(self):
        self.set_old_model()
        self.allow_face_reset()
        self.api("/api/admin/verify-password", password="test-password-123")
        response, extract = self.register()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "Adding an admin needs a face confirmation.")
        extract.assert_not_called()

    def test_face_reset_permission_is_used_up_by_reenroll(self):
        self.set_old_model()
        self.allow_face_reset()
        self.api("/api/admin/verify-password", password="test-password-123")
        with patch.object(face, "extract_face_embedding", return_value=[0.3] * 128):
            self.assertEqual(self.api("/api/admin/face", faceImage=PHOTO).status_code, 200)
        self.set_old_model()
        again = self.api("/api/admin/verify-password", password="test-password-123")
        self.assertEqual(again.status_code, 403)

    def test_used_up_check_cannot_be_replayed_with_old_cookie(self):
        self.verify()
        saved = self.client.get_cookie("session", domain="admin.localhost").value
        self.assertEqual(self.register()[0].status_code, 200)
        self.client.set_cookie("session", saved, domain="admin.localhost")
        replayed, extract = self.register(email="third@example.com")
        self.assertEqual(replayed.status_code, 403)
        extract.assert_not_called()

    def test_step_up_locks_after_five_failures(self):
        for _ in range(5):
            self.assertEqual(self.verify(result=False)[0].status_code, 401)
        locked, verify = self.verify(result=True)
        self.assertEqual(locked.status_code, 429)
        self.assertIn("Too many attempts", locked.get_json()["error"])
        verify.assert_not_called()
        with patch.object(step_up, "now", return_value=step_up.now() + 15 * 60 + 1):
            self.assertEqual(self.verify(result=True)[0].status_code, 200)

    def test_success_resets_failure_count(self):
        for _ in range(4):
            self.verify(result=False)
        self.assertEqual(self.verify(result=True)[0].status_code, 200)
        for _ in range(4):
            self.verify(result=False)
        self.assertEqual(self.verify(result=True)[0].status_code, 200)

    def test_password_fallback_refused_with_usable_face(self):
        response = self.api("/api/admin/verify-password", password="test-password-123")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "Use a face scan to confirm it's you.")

    def test_step_up_endpoints_admin_host_and_csrf(self):
        for path in ("/api/admin/verify-face", "/api/admin/verify-password"):
            with self.subTest(path=path):
                self.assertEqual(self.api(path, base_url="http://localhost").status_code, 404)
                self.assertEqual(self.api(path, csrf=False, password="x", faceImage=PHOTO).status_code, 400)

    # -- pages ----------------------------------------------------------------------
    def test_add_admin_page_shows_step_one_until_verified(self):
        html = self.page("/admins/new")
        self.assertIn('data-flow="verify"', html)
        self.assertNotIn('data-flow="register"', html)
        self.verify()
        html = self.page("/admins/new")
        self.assertIn('data-flow="register"', html)
        self.assertIn("Confirmed", html)

    def test_reenroll_page_explains_operator_step_for_old_model(self):
        self.set_old_model()
        html = self.page("/account/face")
        self.assertIn("allow-face-reset", html)
        self.assertNotIn('data-flow="verify-password"', html)
        self.allow_face_reset()
        html = self.page("/account/face")
        self.assertIn('data-flow="verify-password"', html)
        self.assertNotIn('data-flow="reenroll"', html)

    def test_admin_js_has_step_up_flows(self):
        script = (ROOT / "admin_static" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("/api/admin/verify-face", script)
        self.assertIn("/api/admin/verify-password", script)
        self.assertNotIn("innerHTML", script)
        self.assertTrue(re.search(r"Confirm it.s you first", script))
