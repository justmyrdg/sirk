from datetime import datetime, timezone

from fipconnect.extensions import db


class Admin(db.Model):
    __tablename__ = "admins"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.Text, nullable=False)
    face_embedding = db.Column(db.Text)
    face_model = db.Column(db.String(64))
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # "Confirm it's you" bookkeeping, kept on the server (see services/step_up.py):
    # when a confirmation was last used up, failed attempts and any lockout, and
    # until when an operator has allowed a password-confirmed face reset.
    step_up_used_at = db.Column(db.DateTime(timezone=True))
    step_up_failures = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    step_up_locked_until = db.Column(db.DateTime(timezone=True))
    face_reset_until = db.Column(db.DateTime(timezone=True))

    def to_dict(self):
        return {"username": self.email}
