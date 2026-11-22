from fipconnect.extensions import db
from fipconnect.models._types import BOOKING_STATUSES, in_list, money


class Booking(db.Model):
    __tablename__ = "bookings"
    __table_args__ = (
        db.CheckConstraint(in_list("status", BOOKING_STATUSES), name="ck_bookings_status"),
        db.Index(
            "uq_bookings_confirmed_date",
            "date",
            unique=True,
            postgresql_where=db.text("status = 'Confirmed'"),
        ),
    )

    id = db.Column(db.String(40), primary_key=True)
    inquiry_id = db.Column(
        db.String(40),
        db.ForeignKey("inquiries.id", ondelete="SET NULL"),
        unique=True,
    )
    client_name = db.Column(db.String(120), nullable=False)
    event_name = db.Column(db.String(120), nullable=False)
    date = db.Column(db.Date, nullable=False)
    venue = db.Column(db.String(180), nullable=False, default="")
    status = db.Column(db.String(16), nullable=False, default="Confirmed")
    expected_revenue = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    actual_revenue = db.Column(db.Numeric(14, 2))

    def to_dict(self):
        return {
            "id": self.id,
            "inquiryId": self.inquiry_id,
            "clientName": self.client_name,
            "eventName": self.event_name,
            "date": self.date.isoformat(),
            "venue": self.venue,
            "status": self.status,
            "expectedRevenue": money(self.expected_revenue),
            "actualRevenue": money(self.actual_revenue),
        }
