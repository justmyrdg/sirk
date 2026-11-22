# Separate client and admin front ends — design

Date: 2026-11-21 · Size: small change (short design)

## Intent

Clients must never see the admin: no Admin/login button, no admin code in what
their browser downloads, and no admin API reachable from the client site. On
deployment the admin lives on its own subdomain (e.g. `admin.yoursite.com`).

## Goals / non-goals

- Goal: client site (home, availability, inquiry, status) ships only client code.
- Goal: admin site (login, face login/enrollment, dashboard, all admin tabs) is
  served only on the admin host.
- Goal: server rejects admin API calls that arrive on the client host.
- Goal: close open admin signup — only a signed-in admin can create more admins.
  The very first admin is still created through first-time setup, admin host only.
- Non-goal: changing storage (still the JSON file), visual redesign, or auth methods.
- Anti-goal: anything that makes the admin reachable by path on the client domain
  (e.g. `yoursite.com/admin`).

## Approaches

- **A. One Flask app, routes by request host (chosen).** Same process and data
  file; Host header decides which page/JS is served and which APIs are allowed.
- B. Two Flask apps sharing the JSON file — rejected: two servers to deploy and
  concurrent writers can corrupt the prototype JSON store.
- C. `/admin` path + hosting maps subdomain to it — rejected: admin still
  reachable on the client domain unless hosting is configured perfectly.

## Design

- **Config:** `FIP_ADMIN_HOST` (default `admin.localhost`) names the admin host;
  port is ignored when comparing. `FIP_CLIENT_URL` (default
  `http://localhost:5000`) is used for the admin's "View site"/"Preview site" links.
- **Host check:** a helper `is_admin_host()` compares the request hostname
  (lower-cased, no port) to `FIP_ADMIN_HOST`.
- **Pages:** `/` on the admin host renders `templates/admin.html`; on any other
  host it renders `templates/client.html`.
- **JavaScript split:** `static/js/app.js` becomes
  - `static/js/shared.js` — `api()`, toast, escaping, date helpers, calendar markup;
  - `static/js/client.js` — public pages only; no Admin button, no admin markup,
    no admin endpoint strings;
  - `static/js/admin.js` — admin header, auth, face capture, all admin tabs.
  The CSS stays one shared file.
- **API split:**
  - Public on client host: `/api/bootstrap` (landing, services, available dates,
    CSRF — no `adminConfigured`/`isAdmin`), `POST /api/inquiries`,
    `GET /api/inquiries/<ref>`, `/api/availability`.
  - Admin host only: a new `/api/admin/bootstrap` (adminConfigured, isAdmin,
    CSRF), setup, login, face login, register, face re-enroll, logout, admin data
    and every admin mutation. On the client host these return 404 so their
    existence isn't advertised.
- **Signup:** `/api/register-admin` requires an admin session (`admin_required`).
  The login screen loses its public "Create account" option; a signed-in admin
  gets an "Add admin" action instead. First-time setup is unchanged otherwise.
- **Sessions:** cookies stay host-only (no `SESSION_COOKIE_DOMAIN`), so the client
  site never carries an admin session cookie.
- **Local dev:** clients at `http://localhost:5000`, admin at
  `http://admin.localhost:5000` (browsers resolve `*.localhost` to this machine
  and treat it as secure, so the camera works). Existing 127.0.0.1 → localhost
  redirect stays.
- **Tests:** update `tests/test_app.py` — admin tests use the admin host; add tests
  that client HTML/JS contain no admin strings, admin APIs 404 on the client
  host, and register-admin requires an admin session. README updated.

## Left to the builder

Exact file split boundaries within the JS, wording of the "Add admin" UI, and
test helper structure.
