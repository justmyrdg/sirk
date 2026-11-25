"""The test suite must never send real email or SMS, whatever is in .env."""

import os
import unittest

from tests.base import test_database_uri


class NoRealNotificationsTests(unittest.TestCase):
    def test_env_file_mail_and_sms_settings_are_not_used_by_tests(self):
        test_database_uri()  # loads .env, as every database test does
        for key in ("FIP_SMTP_HOST", "FIP_SMTP_USERNAME", "FIP_SMTP_PASSWORD", "FIP_SMTP_FROM",
                    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"):
            with self.subTest(key=key):
                self.assertNotIn(key, os.environ)
