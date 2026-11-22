"""The home address, and the admin-only script folder."""

from flask import Blueprint, send_from_directory

from fipconnect.config import ROOT
from fipconnect.services.security import admin_host_only, is_admin_host, page_admin_required

bp = Blueprint("pages", __name__)


@bp.get("/")
def index():
    """The same address is the client home page or, on the admin host,
    the admin dashboard."""
    if is_admin_host():
        return admin_dashboard()
    from fipconnect.controllers.client_pages import home

    return home()


@page_admin_required
def admin_dashboard():
    from fipconnect.controllers.workspace_pages import dashboard

    return dashboard()


@bp.get("/admin-static/<path:filename>", endpoint="admin_asset")
@admin_host_only
def admin_asset(filename):
    return send_from_directory(ROOT / "admin_static", filename)
