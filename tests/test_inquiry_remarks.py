"""Remarks on inquiry updates: kept as a history, shown to the client, and sent by email/SMS."""

import os
import re
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from fipconnect.extensions import db
from fipconnect.models import Inquiry, InquiryUpdate
from fipconnect.services import face, inquiries, notifications
from fipconnect.services.errors import ValidationError
from tests.base import DatabaseTestCase

ADMIN = "http://admin.localhost"


def future(days=30):
    return (date.today() + timedelta(days=days)).isoformat()


def csrf_from(html):
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return match.group(1) if match else ""


class RemarksTestCase(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.make_app(ALLOW_SETUP=True)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        with patch.object(notifications, "notify_client") as self.submitted_notify:
            with patch.object(inquiries, "notify_client"):
                self.inquiry = inquiries.submit_inquiry({
                    "name": "Ana Cruz", "email": "ana@example.com", "phone": "09171234567",
                    "eventName": "Garden Wedding", "eventDate": future(), "termsAccepted": True,
                })
        self.inquiry_id = self.inquiry.id

    def updates(self):
        db.session.expire_all()
        return db.session.scalars(
            db.select(InquiryUpdate).where(InquiryUpdate.inquiry_id == self.inquiry_id)
            .order_by(InquiryUpdate.id)
        ).all()

    def change(self, status, remark="", revenue="12000"):
        with patch.object(inquiries, "notify_client") as notify:
            inquiries.change_status(self.inquiry_id, status, revenue, remark)
        return notify


class RemarkRulesTests(RemarksTestCase):
    def test_submitting_records_a_submitted_update(self):
        self.assertEqual([(u.status, u.remark) for u in self.updates()], [("Submitted", "")])

    def test_status_change_with_remark_is_recorded_and_sent(self):
        notify = self.change("Under Review", "  Checking venue availability.  ")
        self.assertEqual(self.updates()[-1].status, "Under Review")
        self.assertEqual(self.updates()[-1].remark, "Checking venue availability.")
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[1:], ("Under Review", "Checking venue availability."))

    def test_status_change_without_remark_is_recorded(self):
        notify = self.change("Under Review")
        self.assertEqual(self.updates()[-1].remark, "")
        self.assertEqual(notify.call_args.args[1:], ("Under Review", ""))

    def test_remark_with_same_status_is_recorded_and_sent(self):
        notify = self.change("Submitted", "We will reply within 2 days.")
        self.assertEqual(len(self.updates()), 2)
        self.assertEqual(notify.call_args.args[1:], ("Submitted", "We will reply within 2 days."))

    def test_save_with_no_change_records_and_sends_nothing(self):
        notify = self.change("Submitted", "   ")
        self.assertEqual(len(self.updates()), 1)
        notify.assert_not_called()

    def test_remark_too_long_is_refused(self):
        with self.assertRaises(ValidationError) as refused:
            self.change("Under Review", "x" * 1001)
        self.assertEqual(refused.exception.message, "Remarks can be at most 1000 characters.")
        db.session.rollback()
        self.assertEqual(len(self.updates()), 1)
        self.assertEqual(db.session.get(Inquiry, self.inquiry_id).status, "Submitted")

    def test_line_breaks_count_once(self):
        # Browsers send each line break as \r\n: 1083 characters as sent, 903 as written.
        remark = ("line\r\n" * 180) + "end"
        self.assertGreater(len(remark), 1000)
        notify = self.change("Under Review", remark)
        self.assertEqual(self.updates()[-1].remark, ("line\n" * 180) + "end")
        notify.assert_called_once()

    def test_remark_only_is_sent_as_a_note(self):
        notify = self.change("Submitted", "We will reply within 2 days.")
        self.assertEqual(notify.call_args.kwargs, {"note_only": True})
        changed = self.change("Under Review", "Checking.")
        self.assertEqual(changed.call_args.kwargs, {"note_only": False})

    def test_history_is_newest_first(self):
        self.change("Under Review", "First")
        self.change("Approved", "Second")
        history = inquiries.history(db.session.get(Inquiry, self.inquiry_id))
        self.assertEqual([u.status for u in history], ["Approved", "Under Review", "Submitted"])


SMTP_ENV = {"FIP_SMTP_HOST": "smtp.example.com", "FIP_SMTP_FROM": "sender@example.com"}
TWILIO_ENV = {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t", "TWILIO_FROM_NUMBER": "+15550001111"}
CLIENT = {"email": "ana@example.com", "name": "Ana", "phone": "09171234567", "reference": "FIP-AAAA2222",
          "eventName": "Garden Wedding", "eventDate": "2026-12-16"}


class RemarkMessagesTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.make_app()

    def email(self, remark):
        smtp = MagicMock()
        with patch.dict(os.environ, SMTP_ENV), patch.object(notifications.smtplib, "SMTP", smtp):
            with self.app.app_context():
                notifications.send_client_email(dict(CLIENT), "Approved", remark)
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        return (message.get_body(preferencelist=("html",)).get_content(),
                message.get_body(preferencelist=("plain",)).get_content())

    def sms(self, remark):
        response = MagicMock(status=201)
        response.__enter__.return_value = response
        with patch.dict(os.environ, TWILIO_ENV), \
                patch.object(notifications.urllib.request, "urlopen", return_value=response) as urlopen:
            with self.app.app_context():
                notifications.send_client_sms(dict(CLIENT), "Approved", remark)
        body = urlopen.call_args.args[0].data.decode()
        from urllib.parse import parse_qs
        return parse_qs(body)["Body"][0]

    def test_email_shows_escaped_remark(self):
        html, text = self.email("Pay <b>50%</b> deposit")
        self.assertIn("Note from the FIP team", html)
        self.assertIn("Pay &lt;b&gt;50%&lt;/b&gt; deposit", html)
        self.assertIn("Note from the FIP team: Pay <b>50%</b> deposit", text)

    def test_note_only_email_does_not_repeat_the_status_news(self):
        smtp = MagicMock()
        with patch.dict(os.environ, SMTP_ENV), patch.object(notifications.smtplib, "SMTP", smtp):
            with self.app.app_context():
                notifications.send_client_email(dict(CLIENT), "Approved", "Send the deposit.", note_only=True)
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        html = message.get_body(preferencelist=("html",)).get_content()
        text = message.get_body(preferencelist=("plain",)).get_content()
        self.assertEqual(message["Subject"], "FIPConnect: a note about your inquiry (FIP-AAAA2222)")
        self.assertIn("A note about your inquiry", html)
        self.assertNotIn("Good news", html)
        self.assertNotIn("Good news", text)
        self.assertIn("Send the deposit.", html)

    def test_note_only_sms_does_not_repeat_the_status_news(self):
        response = MagicMock(status=201)
        response.__enter__.return_value = response
        with patch.dict(os.environ, TWILIO_ENV),                 patch.object(notifications.urllib.request, "urlopen", return_value=response) as urlopen:
            with self.app.app_context():
                notifications.send_client_sms(dict(CLIENT), "Approved", "Send the deposit.", note_only=True)
        from urllib.parse import parse_qs
        body = parse_qs(urlopen.call_args.args[0].data.decode())["Body"][0]
        self.assertNotIn("APPROVED", body)
        self.assertIn("Note: Send the deposit.", body)

    def test_email_without_remark_has_no_note(self):
        html, text = self.email("")
        self.assertNotIn("Note from the FIP team", html)
        self.assertNotIn("Note from the FIP team", text)

    def test_sms_includes_trimmed_remark(self):
        self.assertIn("Note: Bring the contract.", self.sms("Bring the contract."))
        long_body = self.sms("y" * 400)
        self.assertIn("Note: " + "y" * 297 + "...", long_body)
        self.assertNotIn("…", long_body)  # keeps the SMS in the cheaper GSM-7 encoding
        self.assertNotIn("y" * 300, long_body)
        self.assertNotIn("Note:", self.sms(""))

    def test_notify_client_passes_remark_on(self):
        with self.app.app_context(), \
                patch.object(notifications, "send_client_email") as email, \
                patch.object(notifications, "send_client_sms") as sms:
            notifications.notify_client(dict(CLIENT), "Approved", "See you soon", note_only=True)
        self.assertEqual(email.call_args.args[1:], ("Approved", "See you soon"))
        self.assertEqual(email.call_args.kwargs, {"note_only": True})
        self.assertEqual(sms.call_args.kwargs, {"note_only": True})


class RemarkPagesTests(RemarksTestCase):
    def setUp(self):
        super().setUp()
        self.client = self.app.test_client()
        csrf = self.client.get("/api/admin/bootstrap", base_url=ADMIN).get_json()["csrfToken"]
        with patch.object(face, "extract_face_embedding", return_value=[0.1] * 128):
            created = self.client.post(
                "/api/setup-admin", base_url=ADMIN, headers={"X-CSRF-Token": csrf},
                json={"email": "admin@example.com", "password": "test-password-123", "faceImage": "ZmFrZS1pbWFnZQ=="})
        self.assertEqual(created.status_code, 200)

    def admin_html(self, path):
        return self.client.get(path, base_url=ADMIN).get_data(as_text=True)

    def test_admin_saves_remark_from_review_page(self):
        page = self.admin_html(f"/inquiries/{self.inquiry_id}")
        self.assertRegex(page, r'<label for="review-remark">Remarks for the client</label>')
        self.assertRegex(page, r'<textarea id="review-remark" name="remark"[^>]*maxlength="1000"')
        with patch.object(inquiries, "notify_client") as notify:
            saved = self.client.post(f"/inquiries/{self.inquiry_id}", base_url=ADMIN, data={
                "csrf_token": csrf_from(page), "status": "Under Review", "expectedRevenue": "",
                "remark": "Checking the venue."})
        self.assertEqual(saved.status_code, 303)
        self.assertEqual(notify.call_args.args[1:], ("Under Review", "Checking the venue."))
        history = self.admin_html(f"/inquiries/{self.inquiry_id}")
        self.assertIn("Checking the venue.", history)
        self.assertLess(history.index("Under Review</span>"), history.rindex("Submitted</span>"))

    def test_too_long_remark_keeps_the_typed_text(self):
        page = self.admin_html(f"/inquiries/{self.inquiry_id}")
        refused = self.client.post(f"/inquiries/{self.inquiry_id}", base_url=ADMIN, data={
            "csrf_token": csrf_from(page), "status": "Under Review", "expectedRevenue": "",
            "remark": "z" * 1001})
        self.assertEqual(refused.status_code, 400)
        body = refused.get_data(as_text=True)
        self.assertIn("Remarks can be at most 1000 characters.", body)
        self.assertIn("z" * 1001, body)

    def test_client_status_page_shows_timeline_newest_first(self):
        self.change("Under Review", "Checking <venue> availability.")
        self.change("Approved", "Please send the deposit.")
        reference = db.session.get(Inquiry, self.inquiry_id).reference
        status_page = self.client.get("/status").get_data(as_text=True)
        result = self.client.post("/status", data={
            "csrf_token": csrf_from(status_page), "reference": reference}).get_data(as_text=True)
        self.assertIn("Please send the deposit.", result)
        self.assertIn("Checking &lt;venue&gt; availability.", result)
        self.assertLess(result.index("Please send the deposit."), result.index("Checking &lt;venue&gt;"))
        self.assertIn('class="status-timeline"', result)
