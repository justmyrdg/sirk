"""The client status email: a designed HTML email with the logo, plus a plain-text copy."""

import os
from unittest.mock import MagicMock, patch

from fipconnect.services import notifications
from tests.base import DatabaseTestCase

SMTP_ENV = {
    "FIP_SMTP_HOST": "smtp.example.com", "FIP_SMTP_PORT": "587",
    "FIP_SMTP_USERNAME": "sender@example.com", "FIP_SMTP_PASSWORD": "app-password",
    "FIP_SMTP_FROM": "sender@example.com", "FIP_SMTP_USE_SSL": "false",
}
INQUIRY = {"email": "client@example.com", "name": "Ana <Cruz>", "reference": "FIP-ABCD1234",
           "eventName": "Wedding & Reception", "eventDate": "2026-12-16"}


class StatusEmailTests(DatabaseTestCase):
    def send(self, status="Approved"):
        smtp = MagicMock()
        with patch.dict(os.environ, SMTP_ENV), patch.object(notifications.smtplib, "SMTP", smtp):
            app = self.make_app(CLIENT_URL="https://fip.example.com")
            with app.app_context():
                self.assertTrue(notifications.send_client_email(dict(INQUIRY), status))
        return smtp.return_value.__enter__.return_value.send_message.call_args.args[0]

    def parts(self, message):
        html = message.get_body(preferencelist=("html",))
        plain = message.get_body(preferencelist=("plain",))
        return html, plain

    def test_email_has_designed_html_and_plain_text(self):
        message = self.send()
        html, plain = self.parts(message)
        self.assertIsNotNone(html)
        self.assertIsNotNone(plain)
        body = html.get_content()
        self.assertIn("FIP-ABCD1234", body)
        self.assertIn("Approved", body)
        self.assertIn('href="https://fip.example.com/status"', body)
        self.assertIn("Track your inquiry", body)
        self.assertIn("FIP-ABCD1234", plain.get_content())
        self.assertEqual(message["Subject"], "FIPConnect inquiry update: Approved (FIP-ABCD1234)")

    def test_logo_is_embedded_and_shown(self):
        message = self.send()
        html, _ = self.parts(message)
        images = [part for part in message.walk() if part.get_content_type() == "image/png"]
        self.assertEqual(len(images), 1)
        cid = images[0]["Content-ID"].strip("<>")
        self.assertIn(f'src="cid:{cid}"', html.get_content())
        self.assertTrue(images[0].get_payload(decode=True).startswith(b"\x89PNG"))

    def test_client_text_is_escaped_in_html(self):
        body = self.parts(self.send())[0].get_content()
        self.assertIn("Ana &lt;Cruz&gt;", body)
        self.assertIn("Wedding &amp; Reception", body)
        self.assertNotIn("<Cruz>", body)

    def test_status_colours_differ(self):
        approved = self.parts(self.send("Approved"))[0].get_content()
        declined = self.parts(self.send("Declined"))[0].get_content()
        self.assertIn("#1f7a4d", approved)
        self.assertIn("#b42318", declined)

    def test_date_is_written_out(self):
        html, plain = self.parts(self.send())
        self.assertIn("December 16, 2026", html.get_content())
        self.assertIn("December 16, 2026", plain.get_content())

    def test_every_status_gets_the_same_design(self):
        from fipconnect.services.inquiries import STATUSES
        for status in STATUSES:
            with self.subTest(status=status):
                message = self.send(status)
                body = self.parts(message)[0].get_content()
                self.assertIn(notifications.HEADLINES[status], body)
                self.assertIn(notifications.STATUS_COLOURS[status]["text"], body)
                self.assertIn("Track your inquiry", body)
                self.assertEqual(
                    sum(part.get_content_type() == "image/png" for part in message.walk()), 1)
