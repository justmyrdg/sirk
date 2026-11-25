"""Shared test harness: every test runs against TEST_DATABASE_URL only."""

import os
import unittest
from pathlib import Path

from sqlalchemy import text

from fipconnect import create_app
from fipconnect.config import database_url, load_env_file
from fipconnect.extensions import db
from fipconnect.models import seed_defaults

ROOT = Path(__file__).resolve().parents[1]
_schema_ready = False


# Real email/SMS credentials from .env must never reach the tests: tests that
# need them patch their own fake values in.
REAL_NOTIFICATION_SETTINGS = (
    "FIP_SMTP_HOST", "FIP_SMTP_PORT", "FIP_SMTP_USERNAME", "FIP_SMTP_PASSWORD",
    "FIP_SMTP_FROM", "FIP_SMTP_USE_SSL", "FIP_SMTP_TIMEOUT",
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER",
)


def test_database_uri():
    load_env_file(ROOT / ".env")
    for key in REAL_NOTIFICATION_SETTINGS:
        os.environ.pop(key, None)
    uri = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not uri:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. Add it to .env "
            "(a separate database such as fipconnect_test)."
        )
    real = os.environ.get("DATABASE_URL", "").strip()
    if real and database_url(real) == database_url(uri):
        raise RuntimeError(
            "TEST_DATABASE_URL points at the same database as DATABASE_URL. "
            "The tests erase their database, so refusing to run."
        )
    return uri


class DatabaseTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global _schema_ready
        cls.database_uri = test_database_uri()
        if not _schema_ready:
            app = cls.build_app(cls.database_uri)
            with app.app_context():
                try:
                    db.drop_all()
                    with db.engine.begin() as connection:
                        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
                    db.create_all()
                except Exception as error:
                    raise RuntimeError(
                        "Could not reach the test database in TEST_DATABASE_URL."
                    ) from error
            _schema_ready = True

    @staticmethod
    def build_app(uri, **overrides):
        config = {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "SQLALCHEMY_DATABASE_URI": uri,
        }
        config.update(overrides)
        return create_app(config)

    def make_app(self, **overrides):
        return self.build_app(self.database_uri, **overrides)

    def reset_database(self, app):
        with app.app_context():
            tables = ", ".join(table.name for table in db.metadata.sorted_tables)
            db.session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
            seed_defaults(db.session)
            db.session.commit()

    def setUp(self):
        self.db_app = self.make_app()
        self.reset_database(self.db_app)


def mark_schema_dirty():
    """Called by tests that drop the schema so the next class rebuilds it."""
    global _schema_ready
    _schema_ready = False
