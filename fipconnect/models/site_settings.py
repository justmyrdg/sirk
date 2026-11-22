from fipconnect.extensions import db


class SiteSettings(db.Model):
    """The public landing page text. There is always exactly one row (id 1)."""

    __tablename__ = "site_settings"

    id = db.Column(db.Integer, primary_key=True)
    organizer = db.Column(db.String(120), nullable=False)
    headline = db.Column(db.String(160), nullable=False)
    intro = db.Column(db.String(500), nullable=False)

    def to_dict(self):
        return {"organizer": self.organizer, "headline": self.headline, "intro": self.intro}
