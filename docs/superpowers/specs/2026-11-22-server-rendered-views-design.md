# Server-rendered views (HTML out of the JS) — design

Date: 2026-11-22 · Size: project (full design) · Part 2 of 2 (part 1: PostgreSQL + MVC backend, done)

## Intent and why

Both sites are single-page apps whose JavaScript (`static/js/client.js`, 216 lines;
`admin_static/admin.js`, 549 lines) builds every screen from HTML strings. The owner
wants the HTML out of the JS, following best practice and completing the MVC
structure from part 1: models (done) → controllers (done) → **views = Jinja
templates**. They chose server-rendered pages (approach A) over keeping the SPAs
with `<template>` tags (B) or adopting a front-end framework (C).

## Goals

- Every screen is a Jinja template under `templates/`, rendered by a Flask
  controller with data from the models. No HTML is built in JavaScript except
  trivial text updates.
- Same look: templates reuse the existing markup and CSS classes, so
  `static/css/styles.css` needs no or minimal changes.
- Same features and the same validation rules and messages as today.
- Forms work without JavaScript, except the face camera (which needs it).
- The client/admin host split, setup switch, CSRF, and security from earlier
  work are preserved; the client host still serves no admin code or markup.

## Non-goals

- No visual redesign, no new features, no change to models or the database.
- No front-end framework or build step.

## Anti-goals

- Admin HTML or admin URLs reachable on the client host.
- Losing any validation, message, or safety rule from the current API.
- Any POST form without CSRF protection.

## Approaches

- **A. Server-rendered Jinja pages; JS only for small behaviors (chosen).**
  Completes MVC; less JS; search engines can read client pages; every page is
  testable from Python. Costs: biggest rewrite; admin actions reload the page.
- B. Keep SPAs, move markup to `<template>` blocks — rejected: JS still fills
  lists/loops by hand; not MVC.
- C. Front-end framework — rejected: new tooling and build step to move markup.

## Design

### Page map

Client host (main domain):

| URL | Page | Notes |
|---|---|---|
| `GET /` | Home | hero, gallery, active services, CTA |
| `GET /availability?month=YYYY-MM` | Calendar | prev/next links change `month`; available future days link to `/inquire?date=…` |
| `GET /inquire?date=…` | Inquiry form | |
| `POST /inquire` | Submit | on success → `GET /inquire/thanks` showing the reference code (code passed via the session flash, not the URL); on error → re-render the form with the message and the values kept |
| `GET /status`, `POST /status` | Status lookup | POST shows the result on the same page (POST so the code doesn't sit in URLs/history) |

Old links using hashes (`/#inquiry`, `/#status`, `/#availability`) are redirected by
a 5-line script on the home page to the new paths.

Admin host (`FIP_ADMIN_HOST`), every route behind the existing admin-host guard:

| URL | Page |
|---|---|
| `GET /login`, `POST /login` | password login; "Sign in with face" button (JS) |
| `GET /setup`, `POST`-via-JS | first-time setup (only while `FIP_ALLOW_SETUP` and no admins); "setup is turned off" page otherwise |
| `POST /logout` | |
| `GET /` | Dashboard |
| `GET /inquiries` | list; each row links to review |
| `GET /inquiries/<id>`, `POST /inquiries/<id>` | review page (replaces the modal): details + status form |
| `GET /schedule?month=YYYY-MM` | calendar, bookings, block form, blocks list |
| `POST /blocks`, `POST /blocks/<id>/delete` | |
| `GET /bookings/<id>/complete`, `POST` same | record actual revenue (replaces the modal) |
| `GET /services` | list + add form |
| `POST /services`, `GET/POST /services/<id>/edit`, `POST /services/<id>/toggle`, `POST /services/<id>/delete` | |
| `GET /analytics` | |
| `GET /landing`, `POST /landing` | |
| `GET /admins/new` | add-admin page (form + camera, JS) |
| `GET /account/face` | re-enroll face page (camera, JS) |

Any admin page requested while signed out redirects to `/login` (or `/setup` when
no admin exists). Unknown hosts/paths keep returning 404 on the client host.

Destructive actions (delete block, delete service) use a `data-confirm` attribute;
a tiny script asks for confirmation before the form submits.

### Templates

```
templates/
  base.html                      <head>, fonts, CSS, flash-message area, csrf meta
  client/  layout.html home.html availability.html inquire.html thanks.html status.html
  admin/   layout.html (header + sidebar)  login.html setup.html setup_off.html
           dashboard.html inquiries.html inquiry_review.html schedule.html
           booking_complete.html services.html service_edit.html analytics.html
           landing.html admin_new.html face_enroll.html
  partials/ calendar.html  status_pill.html  inquiry_table.html  bookings_table.html
            face_camera.html  form_errors.html
```

Jinja autoescaping replaces `escapeHtml`. Date/money formatting moves to Jinja
filters registered in `create_app`: `date_ph` ("Nov 16, 2027"), `month_ph`,
`peso` ("₱12,000"). The calendar is built server-side by a helper
`calendar_weeks(year, month)` in `fipconnect/services/calendar.py`.

"Today" for past-date logic is the server's date, same as the API used.

### Controllers

The JSON API from part 1 is retired except the endpoints the face camera needs.
Business rules move out of the API handlers into service functions so the HTML
controllers call them (and tests can call them directly):

- `services/inquiries.py`: `submit_inquiry(form) -> Inquiry`, `change_status(inquiry_id, status, expected_revenue) -> None`
- `services/schedule.py`: `block_date(day, reason)`, `unblock(block_id)`, `complete_booking(booking_id, revenue)`
- `services/catalog.py`: `add_service`, `edit_service`, `toggle_service`, `delete_service`, `update_landing`
- `services/accounts.py`: `authenticate(email, password) -> Admin | None`, setup/register helpers

Each raises `ValidationError(message, status)` (new, in `services/errors.py`)
carrying exactly today's message; controllers turn it into a re-rendered form
with that message (and the right HTTP status: 400/404/409). The locking,
transactions, and rollback rules from part 1 move with the code unchanged.

Controllers: `controllers/client_pages.py`, `controllers/admin_pages.py`,
`controllers/auth.py` (login/logout/setup pages + face JSON endpoints).
`controllers/public.py` and `controllers/admin.py` (JSON) are removed.

Kept JSON endpoints (camera flows only, admin host only, unchanged contracts):
`POST /api/setup-admin`, `POST /api/register-admin`, `POST /api/login/face`,
`POST /api/admin/face`, and `GET /api/admin/bootstrap` (for the CSRF token the
camera script sends).

### CSRF

All POST forms include a hidden `csrf_token` (the existing session token);
a `before_request` check rejects POSTs without a matching token (form field or
`X-CSRF-Token` header) with 400 and the existing "Your session expired…"
message rendered on the page. This now also covers the public inquiry and status
forms (each host has its own session, so this is safe).

### JavaScript after the change

- `static/js/site.js` (client): gallery arrows/counter, hash-redirect, `data-confirm`.
- `admin_static/admin.js` (admin): `data-confirm`, and the face camera flows
  (setup, login, add admin, re-enroll) posting to the kept JSON endpoints, then
  navigating on success. Only text/attribute updates, no HTML strings.
- `static/js/shared.js` and `static/js/client.js` are deleted.

### Messages

Success and error notices use Flask `flash()` and render in the layout's notice
area (replacing the JS toast). Validation errors on a form re-render that form
with the message and the user's input preserved (passwords excepted).

### Tests

- Python tests (unittest, test database as in part 1) for every page: renders
  200 with key content; each form's success path (DB changed, redirect, flash);
  each validation rule (same messages as today); auth redirects; admin pages 404
  on the client host; client pages contain no admin strings; CSRF rejection.
- Existing API tests for retired endpoints are rewritten as form tests that keep
  their assertions on behavior (DB state, messages, status codes).
- Concurrency/lock tests from part 1 move to the service layer.
- Face JSON endpoint tests keep their checks on the face endpoints; only their
  sign-in/sign-out/session steps move to the new login/logout forms and dashboard
  page (the retired `/api/login`, `/api/logout`, `/api/admin/data` are not kept
  alive for tests).
- A manual browser check of both sites is part of delivery.

## Calls made without the owner (for review)

- Modals become their own pages (review inquiry, edit service, complete booking).
- The JSON API is retired except the face-camera endpoints; old hash links redirect.
- Public inquiry and status forms now require a CSRF token too.
- `/` serves the home page on the client host and the dashboard on the admin host.
- On HTML pages, "database unavailable" and "changed by someone else" show the same
  messages and status codes as an error page; JSON stays under `/api/`.
- The outdated admin banner ("stored as a JSON file") is removed.
- Camera errors show in a message area on the camera's page (replacing the toast).

## Left to the builder

Exact template boundaries/partials, filter names, helper signatures beyond the
ones named, CSS touch-ups needed for new page-based layouts (e.g. review page
instead of modal), and test structure.
