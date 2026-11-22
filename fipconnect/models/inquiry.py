from datetime import datetime, timezone

from fipconnect.extensions import db
from fipconnect.models._types import STATUSES, in_list, money


class Inquiry(db.Model):
    __tablename__ = "inquiries"
    __table_args__ = (
        db.CheckConstraint(in_list("status", STATUSES), name="ck_inquiries_status"),
    )

    id = db.Column(db.String(40), primary_key=True)
    reference = db.Column(db.String(20), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    event_name = db.Column(db.String(120), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    venue = db.Column(db.String(180), nullable=False, default="")
    guests = db.Column(db.Integer)
    budget = db.Column(db.Numeric(14, 2))
    service = db.Column(db.String(100), nullable=False, default="")
    notes = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(32), nullable=False, default="Submitted")
    terms_accepted = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "reference": self.reference,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "eventName": self.event_name,
            "eventDate": self.event_date.isoformat(),
            "venue": self.venue,
            "guests": self.guests,
            "budget": money(self.budget),
            "service": self.service,
            "notes": self.notes,
            "status": self.status,
            "createdAt": self.created_at.astimezone(timezone.utc).isoformat(),
            "termsAccepted": self.terms_accepted,
        }
