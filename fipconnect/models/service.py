from fipconnect.extensions import db


class Service(db.Model):
    __tablename__ = "services"

    id = db.Column(db.String(40), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(240), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    position = db.Column(db.Integer, nullable=False, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "active": self.active,
        }
