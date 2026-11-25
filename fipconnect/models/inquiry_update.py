from datetime import datetime, timezone

from fipconnect.extensions import db
from fipconnect.models._types import STATUSES, in_list


class InquiryUpdate(db.Model):
    """One step in an inquiry's history: its status at that moment and an
    optional remark for the client."""

    __tablename__ = "inquiry_updates"
    __table_args__ = (
        db.CheckConstraint(in_list("status", STATUSES), name="ck_inquiry_updates_status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    inquiry_id = db.Column(
        db.String(40), db.ForeignKey("inquiries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status = db.Column(db.String(32), nullable=False)
    remark = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
