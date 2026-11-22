from fipconnect.extensions import db


class Block(db.Model):
    __tablename__ = "blocks"

    id = db.Column(db.String(40), primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    reason = db.Column(db.String(120), nullable=False, default="")

    def to_dict(self):
        return {"id": self.id, "date": self.date.isoformat(), "reason": self.reason}
