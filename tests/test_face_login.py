"""Signing in: password first, then a face scan matched against that account's own face."""

import re
from unittest.mock import patch

from fipconnect.extensions import db
from fipconnect.models import Admin
from fipconnect.services import face, security, step_up
from tests.base import DatabaseTestCase

ADMIN = "http://admin.localhost"
PHOTO = "ZmFrZS1pbWFnZQ=="
TIMED_OUT = "Sign-in timed out. Enter your password again."


def csrf_from(html):
    match = re.search(r'name="csrf-token" content="([^"]+)"', html)
    if match is None:
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return match.group(1) if match else ""


class FaceLoginBase(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.make_app(ALLOW_SETUP=True)
        self.client = self.app.test_client()
        csrf = self.get("/api/admin/bootstrap").get_json()["csrfToken"]
        with patch.object(face, "extract_face_embedding", return_value=[0.1] * 128):
            created = self.client.post(
                "/api/setup-admin", base_url=ADMIN, headers={"X-CSRF-Token": csrf},
                json={"email": "admin@example.com", "password": "test-password-123", "faceImage": PHOTO},
            )
        self.assertEqual(created.status_code, 200)
        self.logout()

    # -- helpers ------------------------------------------------------------------
    def get(self, path):
        return self.client.get(path, base_url=ADMIN)

    def logout(self):
        return self.client.post("/logout", base_url=ADMIN, data={})

    def admin_row(self, email="admin@example.com"):
        with self.app.app_context():
            return db.session.scalar(db.select(Admin).where(Admin.email == email))

    def password_login(self, password="test-password-123"):
        token = csrf_from(self.get("/login").get_data(as_text=True))
        return self.client.post("/login", base_url=ADMIN, data={
            "email": "admin@example.com", "password": password, "csrf_token": token})

    def csrf(self):
        return self.get("/api/admin/bootstrap").get_json()["csrfToken"]

    def api(self, path, **body):
        return self.client.post(path, base_url=ADMIN, headers={"X-CSRF-Token": self.csrf()}, json=body)

    def face_step(self, result=True):
        kwargs = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
        with patch.object(face, "verify_face_embedding", **kwargs) as verify:
            response = self.api("/api/login/face", faceImage=PHOTO)
        return response, verify


class FaceLoginTests(FaceLoginBase):
    def test_password_alone_does_not_sign_in(self):
        response = self.password_login()
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/login/face"))
        self.assertTrue(self.get("/").headers["Location"].endswith("/login"))
        # Review Focus 3: an admin API sees a pending sign-in as signed out.
        self.assertEqual(self.api("/api/admin/verify-face", faceImage=PHOTO).status_code, 401)

    def test_face_match_completes_sign_in(self):
        self.password_login()
        response, verify = self.face_step(True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(verify.call_args.args[1], [0.1] * 128)
        self.assertEqual(self.get("/").status_code, 200)

    def test_face_mismatch_refused(self):
        self.password_login()
        response, _ = self.face_step(False)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "Face not recognized. Please try again.")
        self.assertTrue(self.get("/").headers["Location"].endswith("/login"))

    def test_other_admins_face_is_not_used(self):
        with self.app.app_context():
            db.session.add(Admin(
                email="other@example.com", password_hash="x",
                face_embedding=face.encrypt_face_embedding(self.app.secret_key, [0.9] * 128),
                face_model=face.FACE_MODEL,
            ))
            db.session.commit()
        self.password_login()
        _, verify = self.face_step(True)
        verify.assert_called_once()
        self.assertEqual(verify.call_args.args[1], [0.1] * 128)

    def test_pending_expires_after_five_minutes(self):
        with patch.object(security, "now", return_value=1000.0):
            self.password_login()
        with patch.object(security, "now", return_value=1301.0):
            response, verify = self.face_step(True)
            page = self.get("/login/face")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], TIMED_OUT)
        verify.assert_not_called()
        self.assertTrue(page.headers["Location"].endswith("/login?expired=1"))

    def test_face_step_without_password_refused(self):
        response, verify = self.face_step(True)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], TIMED_OUT)
        verify.assert_not_called()

    def test_face_step_locks_after_five_failures(self):
        self.password_login()
        for _ in range(5):
            response, _ = self.face_step(False)
        self.assertEqual(response.status_code, 401)
        locked, verify = self.face_step(True)
        self.assertEqual(locked.status_code, 429)
        verify.assert_not_called()
        later = step_up.now() + 15 * 60 + 1
        with patch.object(step_up, "now", return_value=later):
            self.password_login()
            response, _ = self.face_step(True)
        self.assertEqual(response.status_code, 200)

    def test_success_clears_failures_and_is_not_a_step_up(self):
        self.password_login()
        self.face_step(False)
        self.face_step(False)
        response, _ = self.face_step(True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.admin_row().step_up_failures, 0)
        with patch.object(face, "extract_face_embedding", return_value=[0.2] * 128):
            added = self.api("/api/register-admin", email="new@example.com",
                             password="new-password-123", faceImage=PHOTO)
        self.assertEqual(added.status_code, 403)
        self.assertEqual(added.get_json()["error"], "Confirm it's you first.")

    def test_face_service_error_keeps_pending(self):
        self.password_login()
        down, _ = self.face_step(RuntimeError("The face service is unavailable."))
        self.assertEqual(down.status_code, 503)
        self.assertEqual(self.admin_row().step_up_failures or 0, 0)
        response, _ = self.face_step(True)
        self.assertEqual(response.status_code, 200)

    def test_admin_deleted_between_steps(self):
        self.password_login()
        with self.app.app_context():
            db.session.execute(db.delete(Admin))
            db.session.commit()
        response, verify = self.face_step(True)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], TIMED_OUT)
        verify.assert_not_called()

    def test_login_face_page(self):
        no_pending = self.get("/login/face")
        self.assertTrue(no_pending.headers["Location"].endswith("/login?expired=1"))
        self.password_login()
        html = self.get("/login/face").get_data(as_text=True)
        self.assertIn('data-flow="login"', html)
        self.assertIn('href="/login"', html)
        self.face_step(True)
        signed_in = self.get("/login/face")
        self.assertTrue(signed_in.headers["Location"].endswith("/"))

    def test_login_page_has_no_face_only_button(self):
        html = self.get("/login").get_data(as_text=True)
        self.assertNotIn('data-flow="login"', html)
        self.assertIn("You'll then scan your face.", html)
        self.assertIn(TIMED_OUT, self.get("/login?expired=1").get_data(as_text=True))


class EnrollOnlyTests(FaceLoginBase):
    """Accounts whose saved face can't be checked (none, or an old model)."""

    def setUp(self):
        super().setUp()
        with self.app.app_context():
            admin = db.session.scalar(db.select(Admin))
            admin.face_model = "old-model"
            db.session.commit()

    def enroll(self, **mock):
        mock = mock or {"return_value": [0.3] * 128}
        with patch.object(face, "extract_face_embedding", **mock):
            return self.api("/api/admin/face", faceImage=PHOTO)

    def test_no_face_account_gets_enroll_only(self):
        response = self.password_login()
        self.assertTrue(response.headers["Location"].endswith("/account/face"))
        self.assertTrue(self.get("/").headers["Location"].endswith("/account/face"))
        self.assertTrue(self.get("/admins/new").headers["Location"].endswith("/account/face"))
        html = self.get("/account/face").get_data(as_text=True)
        self.assertIn("Enroll your face", html)
        self.assertIn('data-flow="reenroll"', html)
        self.assertNotIn('data-flow="verify"', html)

    def test_enroll_only_blocks_other_apis(self):
        self.password_login()
        response = self.api("/api/register-admin", email="x@example.com",
                            password="pw-123456789", faceImage=PHOTO)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "Enroll your face first.")
        verify = self.api("/api/admin/verify-password", password="test-password-123")
        self.assertEqual(verify.get_json()["error"], "Enroll your face first.")

    def test_enrolling_needs_no_step_up_and_lifts_restriction(self):
        self.password_login()
        response = self.enroll()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.admin_row().face_model, face.FACE_MODEL)
        self.assertEqual(self.get("/").status_code, 200)

    def test_failed_enrollment_keeps_restriction(self):
        self.password_login()
        response = self.enroll(side_effect=ValueError("No face was detected."))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(self.get("/").headers["Location"].endswith("/account/face"))

    def test_enroll_only_logout_works(self):
        self.password_login()
        signed_out = self.logout()
        self.assertTrue(signed_out.headers["Location"].endswith("/login"))
        self.assertTrue(self.get("/account/face").headers["Location"].endswith("/login"))

    def test_after_enrolling_next_sign_in_needs_face(self):
        self.password_login()
        self.enroll()
        self.logout()
        response = self.password_login()
        self.assertTrue(response.headers["Location"].endswith("/login/face"))

    def test_replayed_enroll_only_cookie_cannot_replace_a_saved_face(self):
        self.password_login()
        old_cookie = self.client.get_cookie("session", domain="admin.localhost").value
        self.assertEqual(self.enroll().status_code, 200)
        self.client.set_cookie("session", old_cookie, domain="admin.localhost")
        replay = self.enroll(return_value=[0.7] * 128)
        self.assertEqual(replay.status_code, 403)
        self.assertEqual(replay.get_json()["error"], "Confirm it's you first.")
