"""Controllers: one blueprint per area.

pages            /  (client home or admin dashboard) and /admin-static/
client_pages     client site: availability, inquire, status
admin_pages      admin sign-in, setup, add admin, re-enroll face
workspace_pages  admin workspace: inquiries, schedule, services, analytics, landing
auth             JSON endpoints used by the face camera
"""


def register_blueprints(app):
    from fipconnect.controllers import admin_pages, auth, client_pages, pages, workspace_pages

    for module in (pages, client_pages, admin_pages, workspace_pages, auth):
        app.register_blueprint(module.bp)
