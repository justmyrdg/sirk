class ValidationError(Exception):
    """A request the business rules refuse. `message` is shown to the user
    as-is and `status` is the HTTP status the page or API answers with."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def reject(message, status=400, rollback=False):
    """Raise a ValidationError, first undoing any open changes if asked."""
    if rollback:
        from fipconnect.extensions import db

        db.session.rollback()
    raise ValidationError(message, status)
