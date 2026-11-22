"""Command-line tools (flask --app app <command>)."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import click
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from fipconnect.config import ROOT
from fipconnect.extensions import db
from fipconnect.models import (
    BOOKING_STATUSES,
    STATUSES,
    Admin,
    Block,
    Booking,
    Inquiry,
    Service,
    SiteSettings,
)
from fipconnect.models._types import as_decimal

DEFAULT_EXPORT = ROOT / "instance" / "fipconnect.json"


class ImportRefused(Exception):
    """The file can't be imported; nothing was changed."""


def _require(condition, record_kind, record_id, problem):
    if not condition:
        raise ImportRefused(f"{record_kind} {record_id!r}: {problem}. Nothing was imported.")


def _parse_date(value, kind, record_id):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ImportRefused(f"{kind} {record_id!r}: invalid date {value!r}. Nothing was imported.")


def _parse_timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _money(value, kind, record_id):
    if value in (None, ""):
        return None
    try:
        return as_decimal(float(value))
    except (TypeError, ValueError):
        raise ImportRefused(f"{kind} {record_id!r}: invalid amount {value!r}. Nothing was imported.")


def _admins(data):
    admins = data.get("admins")
    if not isinstance(admins, list) or not admins:
        admins = [data["admin"]] if isinstance(data.get("admin"), dict) else []
    for record in admins:
        email = str(record.get("email") or record.get("username") or "").strip().lower()
        _require(email and record.get("passwordHash"), "Admin", email or "?", "missing email or password hash")
        yield Admin(
            email=email,
            password_hash=record["passwordHash"],
            face_embedding=record.get("faceEmbedding"),
            face_model=record.get("faceModel"),
            created_at=datetime.now(timezone.utc),
        )


def _inquiries(data):
    for record in data.get("inquiries") or []:
        record_id = record.get("id")
        _require(record_id and record.get("reference"), "Inquiry", record_id, "missing id or reference")
        _require(record.get("status") in STATUSES, "Inquiry", record_id, f"unknown status {record.get('status')!r}")
        yield Inquiry(
            id=record_id,
            reference=record["reference"],
            name=record.get("name", ""),
            email=record.get("email", ""),
            phone=record.get("phone", ""),
            event_name=record.get("eventName", ""),
            event_date=_parse_date(record.get("eventDate"), "Inquiry", record_id),
            venue=record.get("venue") or "",
            guests=record.get("guests"),
            budget=_money(record.get("budget"), "Inquiry", record_id),
            service=record.get("service") or "",
            notes=record.get("notes") or "",
            status=record["status"],
            terms_accepted=record.get("termsAccepted") is True,
            created_at=_parse_timestamp(record.get("createdAt")),
        )


def _bookings(data):
    for record in data.get("bookings") or []:
        record_id = record.get("id")
        _require(record_id, "Booking", record_id, "missing id")
        _require(record.get("status") in BOOKING_STATUSES, "Booking", record_id, f"unknown status {record.get('status')!r}")
        yield Booking(
            id=record_id,
            inquiry_id=record.get("inquiryId"),
            client_name=record.get("clientName", ""),
            event_name=record.get("eventName", ""),
            date=_parse_date(record.get("date"), "Booking", record_id),
            venue=record.get("venue") or "",
            status=record["status"],
            expected_revenue=_money(record.get("expectedRevenue"), "Booking", record_id) or 0,
            actual_revenue=_money(record.get("actualRevenue"), "Booking", record_id),
        )


def _blocks(data):
    for record in data.get("blocks") or []:
        record_id = record.get("id")
        _require(record_id, "Block", record_id, "missing id")
        yield Block(
            id=record_id,
            date=_parse_date(record.get("date"), "Block", record_id),
            reason=record.get("reason") or "",
        )


def _services(data):
    for position, record in enumerate(data.get("services") or []):
        _require(record.get("id"), "Service", record.get("id"), "missing id")
        yield Service(
            id=record["id"],
            name=record.get("name", ""),
            description=record.get("description", ""),
            active=record.get("active") is not False,
            position=position,
        )


def import_json(path):
    """Copy a FIPConnect JSON export into the (empty) database in one transaction."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ImportRefused(f"File not found: {path}")
    except json.JSONDecodeError as error:
        raise ImportRefused(f"{path} is not valid JSON ({error}).")
    if not isinstance(data, dict):
        raise ImportRefused(f"{path} does not look like a FIPConnect export.")

    has_admins = db.session.scalar(select(func.count()).select_from(Admin))
    has_inquiries = db.session.scalar(select(func.count()).select_from(Inquiry))
    if has_admins or has_inquiries:
        raise ImportRefused(
            "The database already has data (admins or inquiries), so nothing was imported."
        )

    counts = {}
    try:
        # Parents first, so bookings can point at their inquiries.
        groups = [
            ("admins", list(_admins(data))),
            ("inquiries", list(_inquiries(data))),
            ("bookings", list(_bookings(data))),
            ("blocks", list(_blocks(data))),
        ]
        services = list(_services(data))
        for name, rows in groups:
            db.session.add_all(rows)
            db.session.flush()
            counts[name] = len(rows)
        if services:
            db.session.execute(delete(Service))
            db.session.add_all(services)
            db.session.flush()
        counts["services"] = len(services) or db.session.scalar(select(func.count()).select_from(Service))
        landing = data.get("landing")
        if isinstance(landing, dict):
            settings = db.session.get(SiteSettings, 1) or SiteSettings(id=1)
            for field in ("organizer", "headline", "intro"):
                if landing.get(field):
                    setattr(settings, field, landing[field])
            db.session.add(settings)
        db.session.commit()
    except ImportRefused:
        db.session.rollback()
        raise
    except IntegrityError as error:
        db.session.rollback()
        detail = str(error.orig).splitlines()[0] if error.orig else "constraint failed"
        raise ImportRefused(f"A record conflicts with another ({detail}). Nothing was imported.")
    except SQLAlchemyError:
        db.session.rollback()
        raise
    return counts


def register_cli(app):
    @app.cli.command("allow-face-reset")
    @click.argument("email")
    @click.option("--minutes", default=60, show_default=True, help="How long the permission lasts.")
    def allow_face_reset_command(email, minutes):
        """Let an admin whose saved face can't be checked confirm with their
        password, once, to re-enroll their face (needs server access)."""
        from fipconnect.services import step_up

        admin = db.session.scalar(select(Admin).where(Admin.email == email.strip().lower()))
        if admin is None:
            click.echo(f"No admin account with email {email!r}.", err=True)
            raise SystemExit(1)
        step_up.allow_face_reset(admin, seconds=minutes * 60)
        click.echo(
            f"Face reset allowed for {admin.email} for {minutes} minutes. They can now sign in, "
            "open Re-enroll face, confirm with their password, and scan their face."
        )

    @app.cli.command("import-json")
    @click.argument("path", required=False, type=click.Path(dir_okay=False, path_type=Path))
    def import_json_command(path):
        """Import an old JSON data file (default: instance/fipconnect.json)."""
        try:
            counts = import_json(path or DEFAULT_EXPORT)
        except ImportRefused as error:
            click.echo(f"Import refused: {error}", err=True)
            raise SystemExit(1)
        click.echo(
            "Imported {admins} admins, {inquiries} inquiries, {bookings} bookings, "
            "{blocks} blocks, {services} services.".format(**counts)
        )
