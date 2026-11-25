# Remarks on inquiry updates — short design

Date: 2026-11-25 · Size: small-to-medium (short design, approved in chat)

## Intent
The FIP team can attach a remark to any inquiry status (e.g. "Please send the 50% deposit
by Dec 10"), and the client sees it on the status page, in the email and in the SMS.

## Decisions (user)
- **Full history**: every update keeps its date, status and remark; the client sees a timeline.
- **A new remark notifies**, even when the status is unchanged.

## Approaches
- **History table `inquiry_updates` (chosen)** — nothing is lost; timeline is a simple query.
- One `remarks` column on inquiries (latest only) — rejected by the user's choice.

## Design
- Table `inquiry_updates`: id, inquiry_id (FK → inquiries, cascade delete), status (same
  check as inquiries), remark (text, default ""), created_at (tz). Migration 0003 creates it and
  backfills one "Submitted" row at each inquiry's created_at, plus a row for the current status
  (dated now) when it isn't "Submitted".
- Submitting an inquiry records a "Submitted" update.
- `change_status(inquiry_id, status, expected_revenue, remark="")`: remark is stripped,
  max 1000 chars (longer → "Remarks can be at most 1000 characters."). If status changed or remark
  non-empty → record an update and notify the client with the remark. Otherwise nothing recorded, no
  notification.
- Admin review page: "Remarks for the client" textarea (optional) + history list (newest first).
- Client status page: timeline, newest first: status pill, date, remark.
- Email: "Note from the FIP team" box when there is a remark (HTML) / "Note from the FIP team:" (text).
- SMS: appends "Note: <remark>", remark cut to 300 characters with "…".
- Remarks are plain text; escaped everywhere (Jinja autoescape; SMS is plain).

## Tests
Update recorded on submit / status change / remark-only; no-op save records nothing and sends
nothing; remark too long refused; notify receives the remark; email HTML+text show the escaped
remark; SMS includes trimmed remark; admin and client pages list history newest first; migration
matches models.

## Left to the builder
Exact wording, layout details, helper names.
