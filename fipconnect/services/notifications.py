"""Client notifications by email (SMTP) and SMS (Twilio).

Both are optional: each is skipped unless its settings are present, and a
failure never undoes the saved inquiry or status change."""

import base64
import os
import re
import smtplib
import ssl
import urllib.parse
import urllib.request
from datetime import date
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from flask import current_app, render_template

LOGO = Path("images") / "logo_flare.png"
HEADLINES = {
    "Submitted": "We received your inquiry",
    "Under Review": "Your inquiry is being reviewed",
    "Awaiting Client Response": "We need your response",
    "Approved": "Your inquiry is approved",
    "Declined": "Your inquiry was not approved",
    "Cancelled": "Your inquiry was cancelled",
}
# Badge background / text colour per status.
STATUS_COLOURS = {
    "Submitted": {"background": "#e8eefb", "text": "#173f7a"},
    "Under Review": {"background": "#fff4e5", "text": "#9a4d00"},
    "Awaiting Client Response": {"background": "#fff4e5", "text": "#9a4d00"},
    "Approved": {"background": "#e3f4ea", "text": "#1f7a4d"},
    "Declined": {"background": "#fde8e7", "text": "#b42318"},
    "Cancelled": {"background": "#eef0f3", "text": "#4b5565"},
}
DEFAULT_COLOUR = STATUS_COLOURS["Submitted"]


def written_date(value):
    """'2026-12-16' -> 'December 16, 2026' (anything else is shown as given)."""
    try:
        day = date.fromisoformat(str(value)[:10])
    except ValueError:
        return value
    return f"{day:%B} {day.day}, {day.year}"


def add_designed_version(message, context):
    """Add the branded HTML version, with the logo embedded in the email
    (so it shows without the mail app loading outside images)."""
    logo_cid = make_msgid(domain="fipconnect")
    html = render_template("email/status_update.html", logo_cid=logo_cid[1:-1], **context)
    message.add_alternative(html, subtype="html")
    logo = Path(current_app.static_folder) / LOGO
    if logo.is_file():
        message.get_payload()[1].add_related(
            logo.read_bytes(), "image", "png", cid=logo_cid, filename="logo.png"
        )


def send_client_email(inquiry, status):
    """Send a client update when SMTP settings are configured."""
    host = os.environ.get("FIP_SMTP_HOST")
    username = os.environ.get("FIP_SMTP_USERNAME")
    password = os.environ.get("FIP_SMTP_PASSWORD")
    sender = os.environ.get("FIP_SMTP_FROM") or username
    if not all((host, sender, inquiry.get("email"))):
        current_app.logger.info("Email notification skipped: SMTP is not fully configured.")
        return False

    reference = inquiry.get("reference", "")
    event_name = inquiry.get("eventName", "your event")
    event_date = written_date(inquiry.get("eventDate", ""))
    status_messages = {
        "Submitted": "We have received your event inquiry and our team will review it.",
        "Under Review": "Your event inquiry is currently being reviewed by our team.",
        "Awaiting Client Response": "Our team needs your response before we can proceed with your inquiry.",
        "Approved": "Good news! Your event inquiry has been approved by Flare Infinity Productions. Our team will contact you about the next steps.",
        "Declined": "We are sorry, but your event inquiry was not approved. Please contact our team if you need assistance.",
        "Cancelled": "Your event inquiry has been marked as cancelled. Please contact our team if you believe this is a mistake.",
    }
    message = EmailMessage()
    subject = f"FIPConnect inquiry update: {status} ({reference})"
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = inquiry["email"]
    name = inquiry.get("name", "Client")
    text = status_messages.get(status, "Your inquiry status has been updated.")
    status_url = current_app.config["CLIENT_URL"].rstrip("/") + "/status"
    # Plain-text copy, for mail apps that don't show HTML.
    message.set_content(
        f"Hello {name},\n\n"
        f"{text}\n\n"
        f"Event: {event_name}\nRequested date: {event_date}\n"
        f"Inquiry status: {status}\n"
        f"Tracking/reference code: {reference}\n\n"
        f"You can track your inquiry at {status_url} by entering this code. "
        "Keep this code private. An approved inquiry is subject to the next booking and event-detail steps communicated by FIP.\n\n"
        "Thank you,\nFlare Infinity Productions"
    )
    add_designed_version(message, {
        "subject": subject, "status": status, "headline": HEADLINES.get(status, "Your inquiry was updated"),
        "colour": STATUS_COLOURS.get(status, DEFAULT_COLOUR), "name": name, "message": text,
        "event_name": event_name, "event_date": event_date, "reference": reference, "status_url": status_url,
    })
    port = int(os.environ.get("FIP_SMTP_PORT", "587"))
    timeout = int(os.environ.get("FIP_SMTP_TIMEOUT", "15"))
    use_ssl = os.environ.get("FIP_SMTP_USE_SSL", "false").lower() == "true"
    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    smtp_kwargs = {"host": host, "port": port, "timeout": timeout}
    if use_ssl:
        smtp_kwargs["context"] = ssl.create_default_context()
    with smtp_class(**smtp_kwargs) as smtp:
        smtp.ehlo()
        if not use_ssl:
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)
    return True

def send_client_sms(inquiry, status):
    """Send an SMS through Twilio when its credentials are configured."""
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_FROM_NUMBER")
    to_number = str(inquiry.get("phone", "")).strip().replace(" ", "").replace("-", "")
    if not all((account_sid, auth_token, from_number, to_number)):
        current_app.logger.info("SMS notification skipped: Twilio is not fully configured.")
        return False
    if to_number.startswith("09") and len(to_number) == 11:
        to_number = "+63" + to_number[1:]
    elif to_number.startswith("9") and len(to_number) == 10:
        to_number = "+63" + to_number
    if not re.fullmatch(r"\+[1-9]\d{7,14}", to_number):
        current_app.logger.warning("SMS notification skipped: client phone is not in E.164 format.")
        return False

    reference = inquiry.get("reference", "")
    event_name = inquiry.get("eventName", "your event")
    sms_messages = {
        "Submitted": "We received your FIPConnect inquiry.",
        "Under Review": "Your FIPConnect inquiry is now under review.",
        "Awaiting Client Response": "FIP needs your response to proceed with your inquiry.",
        "Approved": "Good news! Your FIPConnect event inquiry has been APPROVED. FIP will contact you about next steps.",
        "Declined": "Your FIPConnect event inquiry was not approved. Please contact Flare Infinity Productions for assistance.",
        "Cancelled": "Your FIPConnect event inquiry has been marked as cancelled. Contact FIP if you have questions.",
    }
    body = f"{sms_messages.get(status, 'Your inquiry status has been updated.')} Event: {event_name}. Status: {status}. Tracking code: {reference}. Use this code on the FIPConnect website to track your inquiry."
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    data = urllib.parse.urlencode({"From": from_number, "To": to_number, "Body": body}).encode("utf-8")
    credentials = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("ascii")
    sms_request = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(sms_request, timeout=15) as response:
        return 200 <= response.status < 300

def notify_client(inquiry, status):
    # Notification failures must not undo a saved inquiry/status update.
    try:
        send_client_email(inquiry, status)
    except Exception:
        current_app.logger.exception("Unable to send FIPConnect email notification.")
    try:
        send_client_sms(inquiry, status)
    except Exception:
        current_app.logger.exception("Unable to send FIPConnect SMS notification.")
