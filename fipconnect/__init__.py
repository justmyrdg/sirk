"""FIPConnect application package.

Layout (MVC):
  models/       database tables (SQLAlchemy) and their JSON shapes
  controllers/  Flask blueprints: validate input, use models/services, reply
  services/     security, face recognition, notifications, availability, analytics
"""

import ipaddress
import logging
import os
from urllib.parse import urlsplit

from flask import Flask, redirect, render_template, request
from werkzeug.exceptions import NotFound
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm.exc import StaleDataError

from fipconnect.config import ROOT, database_url, load_or_create_secret, settings_from_environment
from fipconnect.extensions import db, migrate

LOGGER = logging.getLogger(__name__)
DATABASE_UNAVAILABLE = "The database is unavailable. Please try again shortly."


def create_app(test_config=None):
    app = Flask(
        __name__,
        root_path=str(ROOT),
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    app.secret_key = os.environ.get("FIPCONNECT_SECRET_KEY") or load_or_create_secret()
    app.config.update(settings_from_environment())
    if test_config:
        app.config.update(test_config)
    app.config["ADMIN_HOST"] = app.config["ADMIN_HOST"].strip().lower()
    # The built-in default is for local development only: when no admin host
    # was configured, admin.localhost is accepted only from this machine, so a
    # spoofed Host header cannot reach the admin on a deployed server.
    app.config["ADMIN_HOST_LOCAL_ONLY"] = app.config["ADMIN_HOST"] == "admin.localhost"
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url(os.environ.get("DATABASE_URL"))

    db.init_app(app)
    migrate.init_app(app, db, directory=str(ROOT / "migrations"))
    from fipconnect import models  # noqa: F401  registers the tables

    from fipconnect.controllers import register_blueprints

    from fipconnect.views import register_views

    register_blueprints(app)
    register_views(app)
    register_hooks(app)

    from fipconnect.cli import register_cli

    register_cli(app)
    return app


def register_hooks(app):
    @app.before_request
    def normalize_loopback_hostname():
        hostname = urlsplit(f"//{request.host}").hostname or ""
        try:
            is_loopback_ip = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback_ip = False
        if not is_loopback_ip:
            return None
        parsed_url = urlsplit(request.url)
        port = parsed_url.port
        netloc = f"localhost:{port}" if port else "localhost"
        return redirect(parsed_url._replace(netloc=netloc).geturl(), code=308)

    from fipconnect.services.security import csrf_protect, wants_json

    app.before_request(csrf_protect)

    def error_response(message, status, title):
        if wants_json():
            return {"error": message}, status
        return render_template("error.html", message=message, title=title), status

    @app.errorhandler(NotFound)
    def not_found(error):
        return error_response("Not found.", 404, "Page not found")

    @app.errorhandler(OperationalError)
    def database_unavailable(error):
        # Log the error type only: the message can contain the connection URL.
        LOGGER.error("Database unavailable (%s).", type(error.orig).__name__)
        db.session.rollback()
        return error_response(DATABASE_UNAVAILABLE, 500, "Something went wrong")

    @app.errorhandler(StaleDataError)
    def changed_concurrently(error):
        db.session.rollback()
        return error_response(
            "That record was changed by someone else. Refresh and try again.", 409, "Please try again"
        )

    @app.errorhandler(RuntimeError)
    def runtime_error(error):
        app.logger.exception("FIPConnect request failed.")
        db.session.rollback()
        return error_response(str(error), 500, "Something went wrong")
