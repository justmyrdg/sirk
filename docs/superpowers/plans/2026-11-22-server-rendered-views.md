# Server-rendered Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace both JavaScript single-page apps with server-rendered Jinja pages, keeping every feature, rule, and message. JavaScript stays only for the gallery, delete confirmations, and the face camera.

**Architecture:**
1. Business rules move from the JSON handlers into service functions that raise `ValidationError(message, status)`.
2. New page controllers (`client_pages.py`, `admin_pages.py`) render templates from those services, and forms post back with a CSRF token.
3. The JSON API is retired, except the face-camera endpoints.

The admin SPA keeps working until Task 5 replaces it, so every task ends green.

**Tech Stack:** Flask 3.1 + Jinja2, Flask-SQLAlchemy (PostgreSQL), unittest, and plain JS with no build step.

**Spec:** `docs/superpowers/specs/2026-11-22-server-rendered-views-design.md`

**Notes:**
- There's no git repo, so there are no commit steps. Before Task 1, back up `fipconnect/`, `templates/`, `static/js/`, `admin_static/`, `tests/` and `README.md` to the scratchpad.
- Test command: `python -m unittest discover -s tests` (venv active).
- Tests use `TEST_DATABASE_URL` through `tests/base.py` (`DatabaseTestCase`, `make_app`, `AdminClient` in `tests/test_app.py`).

## Global Constraints

- Every validation/error message keeps today's exact text, as found in `fipconnect/controllers/public.py`, `admin.py` and `auth.py`.
- **Client host:**
  - No admin URL answers there (404). Its HTML/JS contains none of these strings: `/api/admin`, `register-admin`, `setup-admin`, `/api/login`, `login`, `face`, `Admin`.
  - Admin JS stays in `admin_static/`, served only on the admin host.
- **Forms and CSRF:**
  - Every POST form has `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.
  - Non-`/api/` POSTs without a matching token get 400, rendering "Your session expired. Refresh the page and try again."
  - `/api/` routes keep their own header check.
- **Templates:**
  - Templates reuse the existing CSS classes in `static/css/styles.css`.
  - New CSS only for page layouts that replace modals (`.modal-*` classes may be reused inside a normal page).
  - No HTML strings built in JS.
- **Error pages:**
  - DB-unavailable shows "The database is unavailable. Please try again shortly." (500).
  - Concurrent change shows "That record was changed by someone else. Refresh and try again." (409).
  - Both are HTML on page routes and JSON under `/api/`.
- **Filters:**
  - Dates render like "Nov 16, 2027" (`date_ph`) and months like "November 2027" (`month_ph`).
  - Money renders as `₱12,000` (`peso`; whole pesos with thousands separators, and centavos only when non-zero, e.g. `₱90,000.50`).
- **Kept JSON endpoints** (admin host only, contracts unchanged): `GET /api/admin/bootstrap`, `POST /api/setup-admin`, `POST /api/register-admin`, `POST /api/login/face`, `POST /api/admin/face`.

## Review Focus

1. **A form error must keep what the user typed** (all fields except passwords). Tests: Task 3 `test_inquiry_error_keeps_typed_values` and Task 5 `test_service_edit_error_keeps_typed_values`.
2. **A bad `?month=` value** (`abc`, `2027-13`, empty) shows the current month, never a 500. Tests: Task 3 `test_availability_bad_month_falls_back` and Task 5 `test_schedule_bad_month_falls_back`.
3. **Unknown IDs** (review inquiry, edit service, complete booking) render a 404 page, not a 500. Test: Task 5 `test_unknown_ids_render_404`.
4. **`/inquire/thanks` opened directly** (no fresh submission) redirects to `/inquire`, so it never shows someone else's code. Test: Task 3 `test_thanks_without_submission_redirects`.
5. **An expired or missing CSRF token** on the public inquiry form re-renders the form with the session message and the typed values kept. Test: Task 3 `test_inquiry_without_csrf_rerenders_with_values`.

---

### Task 1: Service layer for business rules

**Files:**
- Create: `fipconnect/services/errors.py`, `inquiries.py`, `schedule.py`, `catalog.py`, `accounts.py`
- Modify: `fipconnect/controllers/public.py`, `admin.py`, `auth.py` (call the services; JSON responses unchanged)
- Create: `tests/test_domain.py`

**Interfaces:**
- Produces:
  - `errors.ValidationError(message: str, status: int = 400)` with attributes `.message` and `.status`.
  - `inquiries.py`:
    - `submit_inquiry(data: Mapping) -> Inquiry`. Keys: `name, email, phone, eventName, eventDate, venue, guests, budget, service, notes, termsAccepted (bool)`. `guests` and `budget` may be `""`, `None`, a number, or a numeric string. It validates exactly like today's `create_inquiry`, in the same order (availability before terms), locks the date, retries references, commits, then calls `notify_client`.
    - `find_by_reference(code: str) -> Inquiry | None`: strip, then upper-case.
    - `change_status(inquiry_id: str, status: str, expected_revenue) -> Inquiry`: today's `update_inquiry` rules, lock, commit, and notify when the status changed.
  - `schedule.py`:
    - `block_date(day: str | None, reason: str) -> Block`
    - `unblock(block_id: str) -> None` (404 "Date block not found.")
    - `complete_booking(booking_id: str, revenue) -> Booking`
  - `catalog.py`:
    - `add_service(name, description) -> Service`
    - `edit_service(service_id, name, description) -> Service`
    - `set_service_active(service_id, active: bool) -> Service`
    - `delete_service(service_id) -> None`
    - `update_landing(organizer, headline, intro) -> SiteSettings`
  - `accounts.py`:
    - `admin_count() -> int`
    - `authenticate(email, password) -> Admin | None`
    - `email_taken(email) -> bool`
    - `new_admin(email, password, embedding) -> Admin` (moved from `auth.py`; `auth.py` imports them from here).
  - Every rejection raises `ValidationError` with today's message and status, after `db.session.rollback()` when anything was locked or changed.

- [ ] **Step 1: Write failing tests** (`tests/test_domain.py`, `DatabaseTestCase`, inside `self.db_app.app_context()`)
- `test_submit_inquiry_creates_reference_and_accepts_form_strings`: strings `guests="100"` and `budget="90000.50"`. The reference matches `^FIP-[A-Z2-9]{8}$`, and `float(inquiry.budget) == 90000.5`.
- `test_submit_inquiry_rules_keep_messages`: a subTest per case, checking `(message, status)`:
  - past date: ("Please choose today or a future event date.", 400)
  - bad email: ("Please enter a valid email address.", 400)
  - `budget="NaN"`: ("Budget must be a non-negative valid amount.", 400)
  - terms false: ("Please agree to the inquiry terms before submitting.", 400)
  - missing name: ("Please provide your name, email, contact number, event type, and date.", 400)
  - an unavailable date, which wins over missing terms: ("That date is no longer available. Please choose another date.", 409)
- `test_change_status_second_approval_same_date_refused`: the second approval raises ("This date is already booked or unavailable.", 409). Afterwards `Booking.query.count() == 1`, and the second inquiry's status is still "Submitted".
- `test_block_date_on_booked_day_refused`: raises ("That date is already unavailable.", 409) and `Block.query.count() == 0`.
- `test_unblock_twice_raises_404`: the second call raises ("Date block not found.", 404).
- `test_complete_booking_rules`:
  - non-number: ("Actual revenue must be a valid number.", 400)
  - `"inf"`: ("Actual revenue must be a valid non-negative amount.", 400)
  - a non-Confirmed booking: ("Only confirmed bookings can be completed.", 409)
- `test_catalog_rules`:
  - empty name: ("Provide a service name and description within the allowed lengths.", 400)
  - unknown id: ("Service not found.", 404)
  - an empty landing field: ("Complete each landing page field within its allowed length.", 400)
- `test_authenticate`: the right password returns the Admin. A wrong password and an unknown email return `None`. Email matching is case-insensitive.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_domain`
Expected: ImportError for `fipconnect.services.errors`.

- [ ] **Step 3: Implement the five modules**

Then make the JSON controllers call them, catching `ValidationError` and returning `api_error(e.message, e.status)`.

- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover -s tests`
Expected: all PASS (the existing 69 + the new ones).

---

### Task 2: View foundation (layout, filters, calendar, CSRF, error pages)

**Files:**
- Create: `templates/base.html`, `templates/error.html`, `templates/partials/calendar.html`, `templates/partials/status_pill.html`, `templates/partials/form_errors.html`
- Create: `fipconnect/views.py` (filters and template globals), `fipconnect/services/calendar.py`
- Modify: `fipconnect/__init__.py` (register filters, the CSRF `before_request`, and HTML-or-JSON error handlers), `fipconnect/services/security.py`
- Create: `tests/test_views_foundation.py`

**Interfaces:**
- Produces:
  - `views.register_views(app)`. It adds:
    - the filters `date_ph(date | str) -> str`, `month_ph(date) -> str`, `peso(number | Decimal | None) -> str` (`None` gives `"—"`);
    - the globals `csrf_token()` and `today()`.
  - `calendar.month_from_param(value: str | None, today: date) -> date`: the first day of the month. Invalid or empty input gives today's month.
  - `calendar.calendar_weeks(month_start: date) -> list[list[date | None]]`: weeks start on Sunday, with `None` padding.
  - `calendar.shift_month(month_start: date, delta: int) -> date`.
  - `partials/calendar.html` is a macro, `calendar(month_start, weeks, cell)`, where `cell` is a caller block receiving each day. Prev/next are links with `?month=YYYY-MM`.
  - `security.csrf_protect()`, registered as `before_request`. It skips safe methods and paths starting with `/api/`. Otherwise it compares `request.form["csrf_token"]` (or the `X-CSRF-Token` header) with the session token. On a mismatch it sets `g.csrf_failed = True` and lets the view run; views re-render with the session-expired message and status 400 (see Tasks 3–5).
  - `security.page_admin_required(view)`:
    - on a non-admin host: `abort(404)`;
    - no admins yet: redirect to `/setup`;
    - not signed in: redirect to `/login`.
  - `security.wants_json() -> bool`: true when `request.path.startswith("/api/")`.
  - The `OperationalError` / `StaleDataError` / 404 handlers render `error.html` with the same message and status when `not wants_json()`.
  - `base.html` has blocks `title`, `head`, `body`, and `scripts`. Its notice area renders `get_flashed_messages(with_categories=True)` as `<div class="notice notice-success|notice-danger">`.

- [ ] **Step 1: Write failing tests**
- `test_filters`:
  - `date_ph(date(2027,11,16)) == "Nov 16, 2027"`
  - `month_ph(date(2027,11,1)) == "November 2027"`
  - `peso(12000) == "₱12,000"`
  - `peso(Decimal("90000.50")) == "₱90,000.50"`
  - `peso(None) == "—"`
- `test_month_from_param_falls_back`: `"abc"`, `"2027-13"`, `""` and `None` all give `date(today.year, today.month, 1)`. `"2027-02"` gives `date(2027,2,1)`.
- `test_calendar_weeks_shape`: for February 2026, there are 4 or 5 weeks of 7. The first `date(2026,2,1)` sits in column 0 (Sunday). The total non-None count is 28.
- `test_html_error_page_when_db_down`: using the unreachable-DB app from the existing test, `GET /availability` gives 500, and the HTML contains "The database is unavailable. Please try again shortly." This one stays RED until Task 3 adds `/availability`; mark it with `@unittest.expectedFailure` now and remove that in Task 3.
- `test_json_error_kept_under_api`: `GET /api/admin/bootstrap` on the admin host with the DB down gives 500 JSON with the same message.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_views_foundation`
Expected: ImportError for `fipconnect.views`.

- [ ] **Step 3: Implement per Interfaces**

- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover -s tests`
Expected: all PASS.

---

### Task 3: Client site as server-rendered pages

**Files:**
- Create: `templates/client/layout.html`, `home.html`, `availability.html`, `inquire.html`, `thanks.html`, `status.html`
- Create: `static/js/site.js`, `fipconnect/controllers/client_pages.py`
- Modify: `fipconnect/controllers/pages.py` (`/` on the client host renders `client/home.html`; the admin host keeps `admin.html` until Task 5) and `fipconnect/controllers/__init__.py`
- Delete: `static/js/client.js`, `templates/client.html`
- Remove from `controllers/public.py`: `/api/bootstrap`, `POST /api/inquiries`, `GET /api/inquiries/<reference>`, `/api/availability`. Delete the file if nothing is left.
- Modify: `tests/test_app.py`. Retire the tests of removed endpoints and replace them with the page tests below. `submit_inquiry` becomes a form-post helper that fetches the token from `GET /inquire`.

**Interfaces:**
- Consumes: Task 1 (`submit_inquiry`, `find_by_reference`), Task 2 (filters, calendar, `csrf_protect`, `base.html`).
- Produces: routes on the client host only. On the admin host they `abort(404)`, except `/`, which `pages.py` owns.
  - `GET /`, `GET /availability`, `GET /inquire`, `POST /inquire`, `GET /inquire/thanks`, `GET /status`, `POST /status`.
  - Successful `POST /inquire` calls `flash(reference, "reference")` and redirects (303) to `/inquire/thanks`. Thanks reads the `reference` category; if there is none, it redirects to `/inquire`.
  - `site.js`:
    - gallery arrows and counter (the same behavior as today);
    - hash redirect `#inquiry|#availability|#status` → `/inquire|/availability|/status` (keeping `?date=`);
    - `[data-confirm]` submit guard.

- [ ] **Step 1: Write failing tests** (in `tests/test_client_pages.py`, `DatabaseTestCase`)
- `test_home_lists_active_services_and_landing`: 200; contains `"Wedding Production"`. After hiding `svc-social` in the DB, `"Social Celebrations"` is gone.
- `test_availability_marks_booked_and_links_free_days`: with a Confirmed booking on day D, `GET /availability?month=<D's month>` contains `data-date="D"` with the class `is-unavailable`. A free future day links to `/inquire?date=`.
- `test_availability_bad_month_falls_back`: `?month=abc` gives 200 and contains `month_ph(today)`.
- `test_inquire_form_prefills_date`: `GET /inquire?date=2027-11-16` has an input `name="eventDate"` with value `2027-11-16`.
- `test_inquiry_success_redirects_to_thanks_with_code`: POST with a token gives 303 to `/inquire/thanks`. Following it, the page contains the `FIP-` code of the single `Inquiry` in the DB.
- `test_thanks_without_submission_redirects`: a fresh client gets `GET /inquire/thanks` → 302/303 to `/inquire`.
- `test_inquiry_error_keeps_typed_values`: a past date gives 400; the page contains "Please choose today or a future event date." and `value="Test Client"`.
- `test_inquiry_without_csrf_rerenders_with_values`: a POST without a token gives 400, "Your session expired. Refresh the page and try again.", and `value="Test Client"`; no Inquiry row.
- `test_status_lookup`:
  - POST `/status` with the lower-case code: 200, containing the event name and `Submitted`;
  - an unknown code: 404, containing "No inquiry was found for that code.";
  - the email is never in the page.
- `test_client_pages_ship_no_admin_code`: `/`, `/availability`, `/inquire` and `/status`, plus `/static/js/site.js` and `/static/js/shared.js` if they still exist, contain none of the Global Constraints strings.
- `test_client_routes_404_on_admin_host`: `/availability`, `/inquire` and `/status` on the admin host give 404.
- Port: `test_rejects_inquiry_for_past_date` and `test_non_finite_budget_is_rejected` become form posts. Delete `test_public_bootstrap_hides_admin_state`, `test_public_inquiry_does_not_depend_on_admin_session_csrf`, `test_public_status_lookup_still_works_on_client_host_while_put_is_blocked` (its PUT-404 part moves to `test_admin_apis_return_404_on_client_host`), and the JSON parts of `test_public_inquiry_and_private_status_lookup`; each is covered by the tests above.
- Remove the `expectedFailure` from Task 2's `test_html_error_page_when_db_down`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_client_pages`
Expected: FAILs/404s for the new routes.

- [ ] **Step 3: Implement the templates and controller**

Copy the markup from the matching `client.js` functions (`homePage`, `availabilityPage`, `inquiryPage`, `statusPage`, the thanks card in `inquirySubmit`) into the templates, using Jinja loops and filters. The status result is the `notice-success` block from `statusSubmit`.

- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover -s tests`
Expected: all PASS.

---

### Task 4: Admin sign-in, setup, add-admin and re-enroll pages (camera JS)

**Files:**
- Create: `templates/admin/layout.html` (the admin header and sidebar from `adminHeader`/`adminNav`, with active-tab highlighting), `login.html`, `setup.html`, `setup_off.html`, `admin_new.html`, `face_enroll.html`, and `templates/partials/face_camera.html`
- Create: `fipconnect/controllers/admin_pages.py` (auth part)
- Rewrite: `admin_static/admin.js`, as camera flows plus `[data-confirm]` only. Keep the existing SPA in a renamed file, `admin_static/admin_spa.js`, served to `admin.html` until Task 5 deletes both.
- Modify: `fipconnect/controllers/auth.py`. Remove the JSON `/api/login` and `/api/logout`, and remove `/api/admin/data` from `admin.py` in Task 5 (not here). Add the page routes below.
- Modify: `tests/test_app.py` (face tests sign in/out through the forms)

**Interfaces:**
- Consumes: Task 1 `accounts.*`, Task 2 `page_admin_required`, `base.html`, `csrf_protect`.
- Produces (admin host only):
  - `GET /login`: if there are no admins, redirect to `/setup`.
  - `POST /login`:
    - success: `sign_in`, then 303 to `/`;
    - failure: 401, re-rendering with "Incorrect email or password." and the email kept.
  - `POST /logout`: `session.clear()`, then 303 to `/login`.
  - `GET /setup`:
    - admins exist: redirect to `/login`;
    - setup switch off: `setup_off.html` (the text from today's admin.js);
    - otherwise: `setup.html`.
  - `GET /admins/new` and `GET /account/face`, both `page_admin_required`.
  - The camera pages carry `data-flow="setup|login|register|reenroll"` and `data-next="/"`. `admin.js` reads the CSRF token from `<meta name="csrf-token">`, POSTs to the kept JSON endpoint, then sets `location = data-next` on success. On error it puts the message in that page's `<div class="notice notice-danger" data-camera-error hidden>`.
  - The login page's "Sign in with face" uses `data-flow="login"` → `/api/login/face`.

- [ ] **Step 1: Write failing tests** (`tests/test_admin_auth_pages.py`)
- `test_login_page_redirects_to_setup_when_no_admins`: `GET /login` on the admin host → `/setup`.
- `test_setup_off_page_when_switch_off`: with `ALLOW_SETUP=False`, `/setup` contains `FIP_ALLOW_SETUP=true`.
- `test_password_login_and_logout_round_trip`:
  - after `setup_admin` (the JSON endpoint, face patched) and logout, POST `/login` with the right password: 303 to `/`;
  - then `GET /admins/new`: 200;
  - POST `/logout`: 303;
  - then `GET /admins/new`: redirect to `/login`.
- `test_wrong_password_rerenders`: 401, "Incorrect email or password.", and the email kept.
- `test_admin_pages_404_on_client_host`: `/login`, `/setup`, `/admins/new` and `/account/face` on the client host give 404.
- `test_camera_pages_have_flow_and_csrf_meta`: `/setup` has `data-flow="setup"`, `/admins/new` has `data-flow="register"`, and both have `<meta name="csrf-token"`.
- `test_admin_js_builds_no_html`: `admin_static/admin.js` contains no `innerHTML` and no `<div`.
- Port the face tests (`test_admin_can_reenroll_face_after_password_login`, `test_signed_in_admin_creates_additional_admins…`, `test_admin_can_sign_in_with_face_recognition`, `test_unmatched_face_does_not_create_admin_session`, `test_admin_can_sign_in_with_email_and_password`, `test_register_admin_requires_signed_in_admin`): sign-in and sign-out go through the `/login` and `/logout` forms. "Session is valid" is checked with `GET /admins/new` → 200 instead of `/api/admin/data` (until Task 5, `/api/admin/data` still exists and may also be used). The checks on the face endpoints themselves stay unchanged.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_admin_auth_pages`
Expected: 404s for the new routes.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover -s tests`
Expected: all PASS.

---

### Task 5: Admin workspace pages, API retirement, docs, browser check

**Files:**
- Create: `templates/admin/dashboard.html`, `inquiries.html`, `inquiry_review.html`, `schedule.html`, `booking_complete.html`, `services.html`, `service_edit.html`, `analytics.html`, `landing.html`, plus `templates/partials/inquiry_table.html` and `bookings_table.html`
- Modify: `fipconnect/controllers/admin_pages.py` (workspace routes) and `fipconnect/controllers/pages.py` (`/` on the admin host renders the dashboard via `page_admin_required`)
- Delete: `fipconnect/controllers/admin.py` (JSON), `templates/admin.html`, `admin_static/admin_spa.js`, `static/js/shared.js`
- Modify: `tests/test_app.py` (retire JSON-workspace tests and port their behavior to forms), `README.md`

**Interfaces:**
- Consumes: Task 1 services, Task 2 foundation, Task 4 layout and `page_admin_required`.
- Produces (admin host, all `page_admin_required`, all POSTs 303 to the list page with `flash(..., "success")` on success; a `ValidationError` re-renders the page with the message and `e.status`):
  - `GET /`: dashboard (4 stats and 5 recent inquiries, as in `dashboardView`).
  - `GET /inquiries`.
  - `GET /inquiries/<id>` and `POST /inquiries/<id>` (fields `status`, `expectedRevenue`) → `change_status`.
  - `GET /schedule?month=`.
  - `POST /blocks` → `block_date`; `POST /blocks/<id>/delete` → `unblock`.
  - `GET /bookings/<id>/complete` and `POST` (field `actualRevenue`) → `complete_booking`.
  - `GET /services` and `POST /services` → `add_service`.
  - `GET /services/<id>/edit` and `POST` → `edit_service`.
  - `POST /services/<id>/toggle` → `set_service_active(id, not current)`.
  - `POST /services/<id>/delete` → `delete_service`.
  - `GET /analytics`, using `analytics(...)` on the to_dict lists.
  - `GET /landing` and `POST /landing` → `update_landing`.
  - Flash texts: "Inquiry updated.", "Date blocked.", "Date unblocked.", "Booking completed.", "Service added.", "Service saved.", "Service hidden." / "Service published.", "Service deleted.", "Landing page updated."
  - Delete buttons carry `data-confirm="Delete this …?"`.
  - The "View site" and "Preview site" links use `CLIENT_URL`.
  - The stale JSON-storage banner is removed.

- [ ] **Step 1: Write failing tests** (`tests/test_admin_pages.py`, signed in through `/login`)
- `test_dashboard_shows_stats_and_recent`: after 2 inquiries, it contains `Total inquiries` and both event names.
- `test_review_approve_creates_booking`: POST `/inquiries/<id>` with status Approved and revenue 12000 → 303. `Booking.query.one().status == "Confirmed"`, and `/schedule?month=<that month>` shows the booking with `₱12,000`.
- `test_second_approval_same_date_shows_409_message`: 409, containing "This date is already booked or unavailable.", with 1 booking.
- `test_block_and_unblock`: blocking a booked day gives 409 "That date is already unavailable."; blocking a free day gives 303 with a Block row; delete gives 303 with none; deleting again gives 404 "Date block not found."
- `test_complete_booking_page`: "inf" gives 400 with the message; 15000 gives 303, and the analytics page shows `₱15,000`.
- `test_services_crud`: add → it appears; edit → the new name shows; toggle → the client home no longer shows it; delete → it's gone.
- `test_service_edit_error_keeps_typed_values`: a 241-char description gives 400, the message, and the typed name kept.
- `test_landing_update_shows_on_client_home`.
- `test_schedule_bad_month_falls_back`: `?month=2027-13` gives 200.
- `test_unknown_ids_render_404`: `/inquiries/nope`, `/services/nope/edit` and `/bookings/nope/complete` give 404 HTML.
- `test_workspace_pages_redirect_when_signed_out`: `/`, `/inquiries` and `/schedule` on the admin host → `/login`.
- `test_workspace_404_on_client_host`: `/inquiries`, `/schedule`, `/services`, `/analytics`, `/landing` and `/admins/new` give 404.
- `test_post_without_csrf_rejected`: POST `/landing` without a token gives 400 with the session message, and the landing is unchanged.
- Retire the tests that target the removed `admin.py` JSON routes and `/api/admin/data` (approval/persist, money-number checks, delete-twice, stale-data, analytics grouping via API, `test_admin_apis_return_404_on_client_host` reduced to the kept endpoints). The behaviors live on in the tests above and in `tests/test_domain.py`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_admin_pages`
Expected: 404s for the new routes.

- [ ] **Step 3: Implement**

Copy the markup from the matching `admin.js` view functions (`dashboardView`, `inquiriesView`, `scheduleView`, `servicesView`, `analyticsView`, `landingView`, `modalMarkup` branches) into the templates.

- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover -s tests`
Expected: all PASS. Also run: `grep -rn "innerHTML" static/js admin_static`, which should return only `site.js`'s gallery counter `textContent` (i.e. no `innerHTML` at all).

- [ ] **Step 5: Browser check**

Start `python -c "import app; app.app.run(port=5055)"` against the real DB. Using Chrome (claude-in-chrome) or curl if it's unavailable:
- **Client site:** home renders with styles; availability month navigation works; the inquiry form shows an error on a past date; the status lookup works.
- **Admin site:** `/login` renders; the password login works if the user provides it, otherwise check that `/login` and `/setup` render. The dashboard and every tab render.

Stop the server and record what was checked.

- [ ] **Step 6: README**

Update the project tree (`templates/client`, `templates/admin`, `templates/partials`, `static/js/site.js`), the "Run locally" URLs (`/availability`, `/inquire`, `/status`; admin `/login`), and remove the mentions of the SPA/toast.
