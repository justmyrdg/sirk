# Separate Client and Admin Front Ends — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve a client-only front end on the main host and an admin-only front end on the admin host, with admin APIs unreachable from the client host and admin signup closed to the public.

**Architecture:** One Flask app (`app.py`, `create_app`) compares the request hostname to `ADMIN_HOST`. `/` renders `client.html` or `admin.html`; admin API routes return 404 on any non-admin host. The current `static/js/app.js` is split into `static/js/shared.js`, `static/js/client.js`, and `admin_static/admin.js` (served only on the admin host).

**Tech Stack:** Python 3.12, Flask 3, unittest (run via pytest or `python -m unittest`), vanilla JS (no bundler).

**Spec:** `docs/superpowers/specs/2026-11-21-separate-admin-frontend-design.md`

**Note:** the project folder is not a git repository, so the plan has no commit steps. Run tests from `C:\Users\Justmyr\Downloads\flare\flare-main` with the venv active: `python -m pytest tests -q`.

## Global Constraints

- Admin host config: env `FIP_ADMIN_HOST`, default `admin.localhost`; compared lower-cased, port ignored. Stored as `app.config["ADMIN_HOST"]`.
- Client URL config: env `FIP_CLIENT_URL`, default `http://localhost:5000`. Stored as `app.config["CLIENT_URL"]`; used for the admin "View site" / "Preview site" links.
- Admin API on a non-admin host → HTTP 404 JSON `{"error": "Not found."}` (never 401 — don't advertise).
- Public endpoints work on every host: `GET /api/bootstrap`, `POST /api/inquiries`, `GET /api/inquiries/<reference>`, `GET /api/availability`.
- `GET /api/bootstrap` returns only `csrfToken`, `landing`, `services`, `availableDates` (no `adminConfigured`, no `isAdmin`).
- `POST /api/register-admin` requires a signed-in admin. `POST /api/setup-admin` stays the only first-admin path.
- Session cookies stay host-only: do not set `SESSION_COOKIE_DOMAIN`.
- Client HTML/JS must contain no admin markup, no admin endpoint strings, no login UI.
- Keep the existing 127.0.0.1 → localhost redirect.

## Review Focus

1. Host header with port and mixed case (`Admin.Localhost:5000`) must be treated as the admin host — test in Task 1.
2. An admin session cookie can't be used through the client host (cookies are host-only, and the client host 404s admin routes anyway) — test in Task 1.
3. `PUT /api/inquiries/<id>` (admin) and `GET /api/inquiries/<reference>` (public) share a path: the client host must 404 the PUT and still serve the GET — test in Task 1.
4. Fetching `/admin-static/admin.js` from the client host must 404, and `client.js` must contain no admin strings — test in Task 2.
5. Fresh install (no admins): `register-admin` must still 401 without a session, so setup is the only way in — test in Task 1.

---

### Task 1: Host-aware server routing and API guards

**Files:**
- Modify: `app.py` (`create_app` config ~line 333; `admin_required` ~line 572; `bootstrap` ~line 697; `setup_admin`, `register_admin`, `login`, `login_face`, `logout` ~lines 722–928)
- Modify: `tests/test_app.py`

**Interfaces:**
- Produces (inside `create_app`):
  - `is_admin_host() -> bool` — `urlsplit(f"//{request.host}").hostname` lower-cased equals `app.config["ADMIN_HOST"]`.
  - `admin_host_only(view)` decorator — returns `api_error("Not found.", 404)` when `not is_admin_host()`.
  - `admin_required` now checks `is_admin_host()` first (404), then the session (401).
  - `GET /api/admin/bootstrap` (admin host only) → `{"adminConfigured": bool, "isAdmin": bool, "csrfToken": str}`.
- Produces (tests): `AdminClient` wrapper in `tests/test_app.py` with `get/post/put/delete(path, **kw)` that call the wrapped Flask test client with `base_url="http://admin.localhost"`.

- [ ] **Step 1: Migrate existing admin tests to the admin host**

In `setUp`, add `self.admin = AdminClient(self.client)` and `self.admin_csrf()` helper returning `self.admin.get("/api/admin/bootstrap").get_json()["csrfToken"]`. Every call to setup/login/login-face/logout/register/admin-face/admin-data/admin mutations, and the CSRF fetch preceding them, goes through `self.admin`. Public calls (`submit_inquiry`, status lookup, `/api/availability`) stay on `self.client`. Replace `adminConfigured` checks with `self.admin.get("/api/admin/bootstrap").get_json()["adminConfigured"]`. Rename `test_public_signup_creates_additional_admins_with_unique_face_templates` → `test_signed_in_admin_creates_additional_admins_with_unique_face_templates`: register the second admin **while still signed in** as the first (remove the logout before `register-admin`). Delete `test_public_signup_is_available_from_login_screen` (replaced in Task 2).

- [ ] **Step 2: Write the new failing tests**

```python
def test_admin_apis_return_404_on_client_host(self):
    for method, path in [
        ("get", "/api/admin/bootstrap"), ("get", "/api/admin/data"),
        ("post", "/api/setup-admin"), ("post", "/api/register-admin"),
        ("post", "/api/login"), ("post", "/api/login/face"),
        ("post", "/api/logout"), ("post", "/api/admin/face"),
        ("put", "/api/inquiries/abc"), ("post", "/api/blocks"),
        ("delete", "/api/blocks/abc"), ("post", "/api/services"),
        ("put", "/api/services/abc"), ("delete", "/api/services/abc"),
        ("put", "/api/bookings/abc/complete"), ("put", "/api/landing"),
    ]:
        with self.subTest(method=method, path=path):
            response = getattr(self.client, method)(path, headers=self.headers(), json={})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.get_json(), {"error": "Not found."})

def test_public_bootstrap_hides_admin_state(self):
    body = self.client.get("/api/bootstrap").get_json()
    self.assertEqual(set(body), {"csrfToken", "landing", "services", "availableDates"})

def test_admin_host_match_ignores_case_and_port(self):
    response = self.client.get("/api/admin/bootstrap", base_url="http://Admin.Localhost:5000")
    self.assertEqual(response.status_code, 200)

def test_admin_session_is_not_usable_from_client_host(self):
    self.setup_admin()
    self.assertEqual(self.admin.get("/api/admin/data").status_code, 200)
    self.assertEqual(self.client.get("/api/admin/data").status_code, 404)

def test_public_status_lookup_still_works_on_client_host_while_put_is_blocked(self):
    reference = self.submit_inquiry().get_json()["reference"]
    self.assertEqual(self.client.get(f"/api/inquiries/{reference}").status_code, 200)
    self.assertEqual(self.client.put(f"/api/inquiries/{reference}", headers=self.headers(), json={}).status_code, 404)

def test_register_admin_requires_signed_in_admin(self):
    csrf = self.admin_csrf()
    with patch.object(fip_app, "extract_face_embedding") as extract:
        response = self.admin.post("/api/register-admin", headers={"X-CSRF-Token": csrf},
            json={"email": "x@example.com", "password": "password-123", "faceImage": "ZmFrZS1pbWFnZQ=="})
    self.assertEqual(response.status_code, 401)
    extract.assert_not_called()
    self.setup_admin(); self.admin.post("/api/logout", headers=self.headers(), json={})
    csrf = self.admin_csrf()
    response = self.admin.post("/api/register-admin", headers={"X-CSRF-Token": csrf},
        json={"email": "x@example.com", "password": "password-123", "faceImage": "ZmFrZS1pbWFnZQ=="})
    self.assertEqual(response.status_code, 401)

def test_admin_host_is_configurable(self):
    app = fip_app.create_app({"TESTING": True, "SECRET_KEY": "k", "DATA_FILE": str(self.data_file),
                              "ADMIN_HOST": "admin.example.com"})
    client = app.test_client()
    self.assertEqual(client.get("/api/admin/bootstrap", base_url="http://admin.example.com").status_code, 200)
    self.assertEqual(client.get("/api/admin/bootstrap", base_url="http://admin.localhost").status_code, 404)
```

(`setup_admin` and the CSRF flow in it use `self.admin`; `self.headers()` uses `self.csrf`, which `setup_admin` updates from the admin response.)

- [ ] **Step 3: Run tests to verify the new ones fail**

Run: `python -m pytest tests -q`
Expected: the seven new tests FAIL (404s/route missing, bootstrap keys); migrated tests fail on `/api/admin/bootstrap` 404.

- [ ] **Step 4: Implement**

- In `create_app` config: `ADMIN_HOST=os.environ.get("FIP_ADMIN_HOST", "admin.localhost").strip().lower()`, `CLIENT_URL=os.environ.get("FIP_CLIENT_URL", "http://localhost:5000")`; after `test_config` update, lower-case `ADMIN_HOST` again.
- Add `is_admin_host()` and `admin_host_only` per Interfaces; make `admin_required` check host first.
- Apply `@admin_host_only` (placed directly under the `@app.<method>` line) to `setup_admin`, `login`, `login_face`, `logout`.
- `register_admin`: add `@admin_required` (it already implies admin host).
- Trim `bootstrap` to the four public keys; add `admin_bootstrap` at `GET /api/admin/bootstrap` with `@admin_host_only` returning the three admin keys (same `isAdmin` lookup the old bootstrap used).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests -q`
Expected: all pass, except `test_flask_template_and_static_asset_routes`, which Task 2 rewrites (it may still pass now).

---

### Task 2: Split the front end into client and admin

**Files:**
- Create: `templates/client.html`, `templates/admin.html`
- Create: `static/js/shared.js`, `static/js/client.js`, `admin_static/admin.js`
- Delete: `templates/index.html`, `static/js/app.js`
- Modify: `app.py` (`index` ~line 693; new `admin_asset` route)
- Modify: `tests/test_app.py`, `README.md`, `.env.example`

**Interfaces:**
- Consumes: `is_admin_host()`, `admin_host_only`, `/api/admin/bootstrap`, `app.config["CLIENT_URL"]` from Task 1.
- Produces:
  - `GET /` → `render_template("admin.html", client_url=app.config["CLIENT_URL"])` on admin host, else `render_template("client.html")`.
  - `GET /admin-static/<path:filename>` (`@admin_host_only`, but use `abort(404)` style plain 404 — a JSON 404 is fine too) → `send_from_directory(ROOT / "admin_static", filename)`.
  - `window.FIP` (from `static/js/shared.js`), used by both scripts:
    - `FIP.state = { csrfToken: "", bootstrapPath: "/api/bootstrap" }` — admin.js sets `bootstrapPath = "/api/admin/bootstrap"`.
    - `FIP.api(path, options)` — current `api()` (app.js:34-71), reading/writing `FIP.state.csrfToken` and refreshing from `FIP.state.bootstrapPath`. Error text should say `http://localhost:5000` instead of `127.0.0.1`.
    - `FIP.escapeHtml`, `FIP.showToast`, `FIP.dateOnly`, `FIP.todayString`, `FIP.getFormData`, `FIP.pill` — moved unchanged.
    - `FIP.brand(linkAttrs)` — current `brand()` with the anchor's `href`/`data-page` attributes supplied by the caller.
    - `FIP.calendarMarkup(calendarDate, renderCell)` — current calendar shell (month label, day names, blanks, legend, move buttons); `renderCell(dateStr, day, isPast) -> string` returns each day cell.

- [ ] **Step 1: Write the failing tests**

```python
def test_client_page_ships_no_admin_code(self):
    html = self.client.get("/").get_data(as_text=True)
    self.assertIn("/static/js/shared.js", html)
    self.assertIn("/static/js/client.js", html)
    for banned in ("admin.js", "admin-static", "Admin"):
        self.assertNotIn(banned, html)
    response = self.client.get("/static/js/client.js")
    script = response.get_data(as_text=True); response.close()
    for banned in ("/api/admin", "register-admin", "setup-admin", "/api/login",
                   "data-page=\"admin\"", "login-form", "face"):
        with self.subTest(banned=banned):
            self.assertNotIn(banned, script)

def test_admin_script_is_only_served_on_admin_host(self):
    self.assertEqual(self.client.get("/admin-static/admin.js").status_code, 404)
    response = self.admin.get("/admin-static/admin.js")
    self.assertEqual(response.status_code, 200); response.close()

def test_admin_page_loads_admin_script_with_client_url(self):
    html = self.admin.get("/").get_data(as_text=True)
    self.assertIn("/static/js/shared.js", html)
    self.assertIn("/admin-static/admin.js", html)
    self.assertNotIn("/static/js/client.js", html)
    self.assertIn('data-client-url="http://localhost:5000"', html)

def test_admin_script_has_add_admin_and_no_public_signup(self):
    response = self.admin.get("/admin-static/admin.js")
    script = response.get_data(as_text=True); response.close()
    self.assertIn('data-action="add-admin"', script)
    self.assertIn('"/api/register-admin"', script)
    self.assertNotIn('data-action="auth-create"', script)
```

Rewrite `test_flask_template_and_static_asset_routes` to check `/static/css/styles.css`, `/static/js/shared.js`, `/static/js/client.js`, `/static/images/logo_flare.png` return 200 on the client host.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests -q`
Expected: the four new tests and the rewritten asset test FAIL.

- [ ] **Step 3: Implement the server side and templates**

Both templates copy `index.html`'s head (fonts, `styles.css`, meta). `client.html`: `<body>` with `#app`, `#toast`, then `shared.js` and `client.js`. `admin.html`: `<title>FIPConnect Admin — Flare Infinity Productions</title>`, `<meta name="robots" content="noindex, nofollow">`, `<body data-client-url="{{ client_url }}">`, `#app`, `#toast`, then `shared.js` and `/admin-static/admin.js`. Update `index()` and add `admin_asset` per Interfaces. Delete `templates/index.html`.

- [ ] **Step 4: Split the JavaScript**

Each file is an IIFE with `"use strict"`, like `app.js` today.

- `static/js/shared.js`: the `FIP` helpers listed in Interfaces.
- `static/js/client.js`: public state (`data` holding `services`, `landing`, `availableDates`; `page`; `calendarDate`), `publicHeader` **without the Admin link**, `footer`, `serviceCards`, `gallerySection`, `homePage`, `pageHeader`, `inquiryPage`, `statusPage`, `availabilityPage` (calendar cell = the current non-admin button branch of app.js:231), `inquirySubmit`, `statusSubmit`, click handling for `data-page` / `data-calendar-*` / `data-gallery-move`, gallery scroll listener, submit handling for `inquiry-form` and `status-form`, and hash routing limited to `home|inquiry|status|availability`. Bootstrap = `GET /api/bootstrap`, which sets `FIP.state.csrfToken`, `landing`, `services`, `availableDates`. No `inquiries`/`bookings` needed: `dayAvailability` uses `availableDates` only.
- `admin_static/admin.js`: sets `FIP.state.bootstrapPath = "/api/admin/bootstrap"` first. Holds the admin state, `refreshAdminData`, `adminHeader`, `adminNav`, all six tab views, `modalMarkup`, face capture, login, and all admin form/action handling from app.js. Bootstrap = `GET /api/admin/bootstrap` (sets `csrfToken`, `adminConfigured`, `isAdmin`), then `refreshAdminData()` if `isAdmin`. Always renders the admin page; no hash routing. Changes from app.js:
  - **Auth screen:** if `!adminConfigured` show only the setup form (`setup-form` → face capture flow `"setup"` → `/api/setup-admin`); otherwise show only the login form plus face login. Remove `adminAuthMode`, the `auth-login`/`auth-create` buttons and handlers, and the stray `admin-create-form` branch.
  - **Add admin:** for a signed-in admin, the header gets `<button class="button button-quiet button-small" data-action="add-admin">Add admin</button>`. It opens a modal of kind `"add-admin"` with form `add-admin-form` (fields `email`, `password`, `confirm`; same inputs as setup). On submit: check that the passwords match (toast `"The passwords do not match."`), close the modal, render, then `startFaceCapture("register", { email, password })`. The `"register"` flow POSTs `/api/register-admin` and toasts `"Admin account added. They can now sign in."` The current admin stays signed in.
  - **Links:** "View site" and "Preview site ↗" become `href="${document.body.dataset.clientUrl}" target="_blank" rel="noopener"`. The brand link points to the Dashboard tab (`data-admin-tab="Dashboard"`).
  - **Schedule calendar:** cell = the current admin `<div>` branch of app.js:230.

Delete `static/js/app.js`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests -q`
Expected: all tests pass.

- [ ] **Step 6: Manual check in a browser**

Run `python app.py`, then:
- Open `http://localhost:5000`: no Admin button. Home, availability, inquiry, and status all work. Submit an inquiry.
- Open `http://admin.localhost:5000`: you get the login or setup screen. Sign in. The new inquiry appears. Add admin opens the camera flow. View site opens the client site in a new tab.
- Open `http://localhost:5000/admin-static/admin.js`: you get 404.

- [ ] **Step 7: Update docs**

- In `README.md`, replace "Run locally" steps 5–6: clients at `http://localhost:5000`, admin at `http://admin.localhost:5000`; first visit to the admin shows first-time setup.
- In the README, replace the paragraph about public signup: additional admins are added by a signed-in admin via **Add admin**.
- Add a "Deploying on a subdomain" section to the README: set `FIP_ADMIN_HOST=admin.yoursite.com` and `FIP_CLIENT_URL=https://yoursite.com`, and point both DNS names at the same app. Without `FIP_ADMIN_HOST`, the default `admin.localhost` answers only requests from the server machine (see Final review fix in the ledger).
- Update the README project structure tree.
- Add `FIP_ADMIN_HOST` and `FIP_CLIENT_URL` with example values to `.env.example`.
