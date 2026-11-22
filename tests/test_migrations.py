import unittest

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import upgrade
from sqlalchemy import text

from fipconnect.extensions import db
from fipconnect.models import Service, SiteSettings
from fipconnect.models.defaults import DEFAULT_LANDING, DEFAULT_SERVICES
from tests.base import DatabaseTestCase, mark_schema_dirty


def drop_everything(app):
    with app.app_context():
        db.drop_all()
        with db.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        DatabaseTestCase.setUpClass()
        cls.app = DatabaseTestCase.build_app(DatabaseTestCase.database_uri)

    @classmethod
    def tearDownClass(cls):
        drop_everything(cls.app)
        mark_schema_dirty()

    def test_migration_matches_models(self):
        drop_everything(self.app)
        with self.app.app_context():
            upgrade()
            with db.engine.connect() as connection:
                diff = compare_metadata(MigrationContext.configure(connection), db.metadata)
            services = [
                {"id": s.id, "name": s.name, "description": s.description, "active": s.active}
                for s in Service.query.order_by(Service.position)
            ]
            landing = db.session.get(SiteSettings, 1).to_dict()
        self.assertEqual(diff, [])
        self.assertEqual(services, DEFAULT_SERVICES)
        self.assertEqual(landing, DEFAULT_LANDING)
