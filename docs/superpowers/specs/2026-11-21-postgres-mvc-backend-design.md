# PostgreSQL + MVC backend — design

Date: 2026-11-21 · Size: project (full design) · Part 1 of 2 (part 2, moving HTML
out of the JS into template files, is a separate design that follows this one)

## Intent and why

FIPConnect stores everything in one JSON file (`instance/fipconnect.json`) and lives
in one 1,300-line `app.py`. The owner is deploying to Render and wants a real
database (PostgreSQL) and a maintainable, best-practice structure (MVC). A JSON file
can't safely serve more than one worker, can't be browsed or queried, and is lost
on Render without a paid disk. A monolithic file is hard to change safely.

## Goals

- All data lives in PostgreSQL, in real tables, accessed through SQLAlchemy models.
- Each request reads/writes only the rows it needs, inside one transaction.
- Code is split into models, controllers (Flask blueprints), and services.
- Schema changes are versioned migrations (Flask-Migrate / Alembic).
- Existing data (currently 1 admin, 2 inquiries, 3 services) is imported once,
  with IDs, reference codes, password hashes and encrypted face templates intact.
- Safe with several gunicorn workers: no double-booking of a date, no duplicate
  reference codes, no two "first admins".
- Local dev uses the owner's local PostgreSQL 17 (user `postgres`); credentials live
  only in `.env`, never in code or committed files.

## Non-goals

- No front-end changes. Every API URL, method, status code, and JSON response shape
  stays exactly as today (camelCase keys, string IDs, numbers as JSON numbers).
  The admin/client host split, CSRF, face login, setup switch, and `.env` loader
  all behave as now.
- No new features, no change to auth methods or to notification wording.
- HTML-in-JS refactor (that is part 2).

## Anti-goals (failure even if it "works")

- Losing or altering imported data; changing the secret key so face templates
  become unreadable; logging the DB password or committing it.
- Tests touching the real `fipconnect` database.
- Any API response change that would break the existing JS.

## Constraints

- Python 3.12, Flask 3, PostgreSQL 17 locally; Render Postgres in production.
- Driver: `psycopg` 3 (`psycopg[binary]`). ORM: `Flask-SQLAlchemy` 3.x
  (SQLAlchemy 2.x style). Migrations: `Flask-Migrate`.
- Face service (Node, `face_service.cjs`) and its HTTP contract are unchanged.
- Tests stay on `unittest` (`python -m unittest discover -s tests`).

## Approaches

- **A. Tables behind the existing "load everything / save everything" helpers.**
  Least code change; routes untouched. Rejected after discussion: not MVC, and
  every save rewrites all rows, which is wasteful and unsafe across workers.
- **B. MVC with SQLAlchemy models; each controller queries what it needs (chosen).**
  Matches the owner's request for MVC and best practice; real transactions and
  constraints; scales to several workers. Costs a rewrite of each route's data
  access, guarded by the existing test suite.
- C. One JSONB row — rejected: not a real database.

## Design

### Package layout

```
app.py                      entry point only: loads .env when run directly,
                            exposes `app = create_app()` for gunicorn
fipconnect/
  __init__.py               create_app(test_config=None): config, extensions,
                            blueprints, before_request hooks, error handlers, CLI
  config.py                 settings read from the environment
  extensions.py             db = SQLAlchemy(), migrate = Migrate()
  models/                   one module per table + __init__ re-exporting them
    admin.py  inquiry.py  booking.py  block.py  service.py  site_settings.py
  controllers/              Flask blueprints (the "C"); thin: validate input,
                            call models/services, return JSON
    pages.py                GET /, GET /admin-static/<path>
    public.py               /api/bootstrap, POST /api/inquiries,
                            GET /api/inquiries/<reference>, /api/availability
    auth.py                 /api/admin/bootstrap, setup-admin, register-admin,
                            login, login/face, logout, admin/face
    admin.py                /api/admin/data, PUT /api/inquiries/<id>, blocks,
                            services, bookings/<id>/complete, landing
  services/                 logic not tied to one request
    security.py             host check, admin_host_only, admin_required,
                            csrf_token, require_csrf, current_admin()
    face.py                 face image validation, Node service process
                            management, extract/verify/match, template
                            encryption/decryption, legacy error translation
    notifications.py        email (SMTP) + SMS (Twilio) + notify_client
    availability.py         unavailable_dates(), lock_date(date)
    analytics.py            analytics() built from queries
  cli.py                    `flask import-json` command
migrations/                 Alembic, with one initial migration committed
```

"View" in this API-only backend = each model's `to_dict()` serializer, which
produces today's exact JSON shapes. (Templates become part of the view layer in part 2.)

### Schema (initial migration)

String primary keys are kept so existing IDs (`inq-…`, `booking-…`, `svc-…`,
`block-…`) and the JS that uses them keep working.

| Table | Columns |
|---|---|
| `admins` | `id` serial PK · `email` varchar(254) unique, stored lower-case · `password_hash` text · `face_embedding` text null (Fernet token) · `face_model` varchar(64) null · `created_at` timestamptz |
| `inquiries` | `id` varchar(40) PK · `reference` varchar(20) unique · `name` varchar(120) · `email` varchar(160) · `phone` varchar(40) · `event_name` varchar(120) · `event_date` date · `venue` varchar(180) default '' · `guests` int null · `budget` numeric(14,2) null · `service` varchar(100) default '' · `notes` text default '' · `status` varchar(32) (CHECK in the 6 statuses) · `terms_accepted` bool · `created_at` timestamptz |
| `bookings` | `id` varchar(40) PK · `inquiry_id` FK→inquiries.id unique null, ON DELETE SET NULL · `client_name` · `event_name` · `date` date · `venue` · `status` varchar(16) (CHECK Confirmed/Completed/Cancelled) · `expected_revenue` numeric(14,2) default 0 · `actual_revenue` numeric(14,2) null · partial UNIQUE index on `date` WHERE status = 'Confirmed' |
| `blocks` | `id` varchar(40) PK · `date` date UNIQUE · `reason` varchar(120) default '' |
| `services` | `id` varchar(40) PK · `name` varchar(100) · `description` varchar(240) · `active` bool · `position` int (keeps display order; new services get max+1) |
| `site_settings` | `id` int PK (always 1) · `organizer` · `headline` · `intro` (the landing page) |

The initial migration seeds the three default services and the default landing
row (same values as `DEFAULT_SERVICES` / `default_state()` today), so a fresh
database behaves like a fresh JSON install.

API mapping: `admin.username` in responses = `email`. Dates serialize as
`YYYY-MM-DD`; `createdAt` as ISO 8601 with offset; numeric columns as JSON
numbers (float), `null` where null — identical to today.

### Concurrency (replaces the global `LOCK`)

- Every request runs in one SQLAlchemy session/transaction; commit on success,
  rollback on error.
- Claiming a date (create inquiry's availability check, approving an inquiry,
  blocking a date) first takes `pg_advisory_xact_lock(<stable int key from the
  date>)`, then checks and writes. The partial unique index on confirmed bookings
  and the unique `blocks.date` are the backstop.
- Reference codes: generate, insert; on unique violation, retry (max 5).
- First-admin setup takes a fixed advisory lock before checking "no admins yet".

### Sessions

The session stores `admin_id` (integer) instead of `admin_username`. Existing
browser sessions are signed out once by this change; that is acceptable.

### Configuration

| Env var | Meaning |
|---|---|
| `DATABASE_URL` | Required. Local: `postgresql+psycopg://postgres:<password>@localhost:5432/fipconnect`. A `postgres://` or `postgresql://` URL (Render's form) is rewritten to `postgresql+psycopg://`. |
| `TEST_DATABASE_URL` | Used by the test suite only; local: `…/fipconnect_test`. |
| existing | `FIP_ADMIN_HOST`, `FIP_CLIENT_URL`, `FIP_ALLOW_SETUP`, `FIPCONNECT_SECRET_KEY`, SMTP/Twilio — unchanged. |
| removed | `FIPCONNECT_DATA_FILE` (JSON storage is gone). |

**Loading `.env`:** `load_env_file()` moves to `fipconnect/config.py`. `app.py`
calls it on import (not only under `__main__`), before `create_app()`, so
`python app.py`, `flask --app app …` and gunicorn all see `.env`. It still never
overrides variables already set (Render's dashboard values win; Render has no
`.env` file). Tests do **not** import `app.py`: they call
`fipconnect.create_app({"SQLALCHEMY_DATABASE_URI": <TEST_DATABASE_URL>, …})`
after loading `.env` themselves, so `DATABASE_URL` is never touched by tests.

If `DATABASE_URL` is missing (and no URI is passed in test config), the app fails
at startup with a clear message.
The secret key source is unchanged (`FIPCONNECT_SECRET_KEY`, else `instance/secret.key`).
The owner's `.env` gets `DATABASE_URL` and `TEST_DATABASE_URL` with the password
they gave; `.env.example` gets placeholders.

### Errors

Database connection/operational errors return HTTP 500
`{"error": "The database is unavailable. Please try again shortly."}` and are
logged without the connection URL. Existing validation messages are unchanged.

### Data import

`flask --app app import-json [PATH]` (default `instance/fipconnect.json`):
- Refuses to run if the database already has any admin or inquiry (prints why).
- Accepts the legacy single `admin` key as well as `admins`.
- Copies every record with its original IDs/reference codes/hashes/templates;
  replaces the seeded services and landing row with the file's.
- Runs in one transaction; prints counts imported. Leaves the JSON file untouched.
- Records that violate the schema (unknown status, duplicate block date, two
  confirmed bookings on one date, booking pointing at a missing inquiry) abort the
  whole import with a message naming the record ID; nothing is half-imported.
  Money is stored to the cent; missing optional fields get today's defaults;
  admins get `created_at` = import time. (The owner's current file — 1 admin,
  2 inquiries, 3 services, no bookings/blocks — was checked and fits.)

### Setting up locally (owner runs, documented in README)

1. `pip install -r requirements.txt`
2. Create the databases `fipconnect` and `fipconnect_test`.
3. `flask --app app db upgrade`
4. `flask --app app import-json`
5. `python app.py`

The builder performs steps 2–4 on the owner's machine as part of delivery.

### Render

Add a Render PostgreSQL database; set the web service's `DATABASE_URL` to its
internal URL. Build command adds `flask --app app db upgrade`. The persistent
disk is no longer needed for data (the secret key is already an env var there).
README's Render section is updated.

The app is not deployed yet. To move local data to Render later: set Render's
`FIPCONNECT_SECRET_KEY` to the exact contents of the local `instance/secret.key`
(otherwise imported face templates can't be decrypted), then run
`import-json` from the owner's machine with `DATABASE_URL` set to the Render
database's external URL. README documents this.

**Several workers:** data access is safe with several gunicorn workers. The face
service is shared: each worker first checks whether a service is already answering
on the port and reuses it. One gap is fixed: if two workers start Node at once,
the loser's process exits (port taken); `ensure_face_service` then re-checks
readiness instead of failing, so it uses the winner's service. The Render start
command becomes `--workers 2 --threads 4`.

### Tests

- Tests use `TEST_DATABASE_URL` (read from `.env`); they never use `DATABASE_URL`.
- Schema created once per test run from the models (`db.create_all()` after
  `drop_all()`), tables truncated (and seeds reinserted) before each test.
- A separate test runs the Alembic migration on an empty schema and checks it
  matches the models (so migrations can't drift).
- Every existing test keeps its assertions; only setup changes (patch targets
  move to `fipconnect.services.face`, JSON-file manipulation becomes model
  manipulation, the legacy single-admin test becomes an import-json test).
- New tests: import-json (counts, IDs preserved, refuses when data exists,
  legacy `admin` key), double-approval of the same date is refused, a block on a
  booked date is refused, DB-unavailable returns the 500 JSON message.
- If the test database is unreachable the suite fails loudly (no silent skip).

## Calls made without the owner (for review)

- Session key changes to `admin_id` (everyone signs in again once).
- `.env` is loaded on import of `app.py`, not only when run directly.
- Import aborts on bad records rather than fixing them silently.
- Render start command moves to 2 workers.
- Local delivery: the builder creates `fipconnect` / `fipconnect_test` with the
  `postgres` account, runs the migration and the import, and adds `DATABASE_URL` /
  `TEST_DATABASE_URL` to the existing `.env` without changing its other lines.

## Left to the builder

Exact module boundaries inside each package, helper names, the advisory-lock key
derivation, test helper structure, and README wording.
