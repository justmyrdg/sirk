# PostgreSQL + MVC Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace JSON-file storage with PostgreSQL via SQLAlchemy models, and split the 1,300-line `app.py` into an MVC package, with no change to any API URL or response.

**Architecture:** A `fipconnect/` package with an app factory, models (`fipconnect/models/`), blueprints as controllers (`fipconnect/controllers/`), and services (`fipconnect/services/`). Alembic migrations live in `migrations/`. `app.py` becomes a thin entry point. Tests run against a separate `fipconnect_test` database.

**Tech Stack:** Python 3.12, Flask 3.1, Flask-SQLAlchemy 3.1.1 (SQLAlchemy 2.x), Flask-Migrate 4.1.0, psycopg 3 (`psycopg[binary]`), PostgreSQL 17, unittest.

**Spec:** `docs/superpowers/specs/2026-11-21-postgres-mvc-backend-design.md`

**Note:** the folder is not a git repo, so there are no commit steps. Before Task 1, back up `app.py`, `tests/`, `requirements.txt`, `README.md`, `.env.example`, and `instance/fipconnect.json` to the scratchpad. Test command throughout: `python -m unittest discover -s tests` (venv active).

## Global Constraints

- API is frozen: every URL, method, status code, error message, and JSON key/shape stays as today. Numbers are JSON numbers (never `Decimal` strings). Dates are `"YYYY-MM-DD"`. `createdAt` is ISO 8601 with offset. IDs are the existing string IDs.
- The DB password appears only in `.env` (`DATABASE_URL`, `TEST_DATABASE_URL`). Never in code, docs, logs, or test output.
- Tests use only `TEST_DATABASE_URL`. They never read `DATABASE_URL` and never import `app.py`.
- The secret-key source is unchanged: `FIPCONNECT_SECRET_KEY`, else `instance/secret.key`.
- `DATABASE_URL` normalization: a URL starting with `postgres://` or `postgresql://` gets the scheme rewritten to `postgresql+psycopg://`.
- DB operational errors return HTTP 500 `{"error": "The database is unavailable. Please try again shortly."}`. The log line never includes the URL.
- Controllers call face functions as module attributes (`face.extract_face_embedding(...)`, after `from fipconnect.services import face`), so tests can patch `fipconnect.services.face.<name>`.
- Requirements to add: `Flask-SQLAlchemy>=3.1,<4`, `Flask-Migrate>=4.1,<5`, `psycopg[binary]>=3.2,<4`.

## Review Focus

1. A `Numeric` column passed to `jsonify` becomes a string. The JS calls `Number()` on it, so a string fails silently. Tests in Task 1 (`to_dict`) and Task 3 assert `isinstance(..., float)`.
2. A 409 returned after the lock has been taken (e.g. approving a date that's already booked) must not leave any partial rows. The Task 3 double-approval test asserts exactly one booking.
3. Face templates must still decrypt after import, because the secret is the same. The Task 4 import test signs in with face login, using the real `decrypt`.
4. Reference lookup stays case-insensitive (`/api/inquiries/fip-xxxx`). The existing test is kept in Task 3.
5. The DB being down at request time returns the 500 JSON, never an HTML traceback. The Task 3 test uses an unreachable port.

---

### Task 1: Package, config, models, migration, test database

**Files:**
- Create: `fipconnect/__init__.py` (temporary minimal `create_app` that sets up config and db only; Task 3 completes it)
- Create: `fipconnect/config.py`, `fipconnect/extensions.py`
- Create: `fipconnect/models/__init__.py`, `admin.py`, `inquiry.py`, `booking.py`, `block.py`, `service.py`, `site_settings.py`, `defaults.py`
- Create: `migrations/` (via `flask db init`), plus the initial revision `migrations/versions/0001_initial.py`
- Create: `tests/base.py`, `tests/test_models.py`, `tests/test_migrations.py`
- Modify: `requirements.txt`, `.env` (add two lines only)

**Interfaces:**
- Produces:
  - `fipconnect.config.load_env_file(path) -> None`: moved unchanged from `app.py`.
  - `fipconnect.config.database_url(raw: str | None) -> str`: normalizes the scheme. Raises `RuntimeError("DATABASE_URL is not set. Add it to .env (see .env.example).")` on empty input.
  - `fipconnect.extensions.db` (`SQLAlchemy()`) and `migrate` (`Migrate()`).
  - Models `Admin`, `Inquiry`, `Booking`, `Block`, `Service`, `SiteSettings`, all exported from `fipconnect.models`. Each has `to_dict() -> dict` producing today's JSON shape. `Admin.to_dict()` returns `{"username": email}`.
  - `fipconnect.models.defaults`: `DEFAULT_SERVICES` (the 3 dicts from `app.py`) and `DEFAULT_LANDING` (organizer, headline, intro as in `default_state()`).
  - `fipconnect.models.seed_defaults(session) -> None`: inserts the default services (positions 0–2) and `SiteSettings(id=1, **DEFAULT_LANDING)`.
  - `tests.base.DatabaseTestCase(unittest.TestCase)`:
    - `make_app(**overrides)`: builds the app with `SQLALCHEMY_DATABASE_URI` = `TEST_DATABASE_URL`.
    - `setUpClass`: loads `.env`, then runs `drop_all` + `create_all` once per process.
    - `setUp`: truncates every table (`RESTART IDENTITY CASCADE`), then runs `seed_defaults`.
    - If `TEST_DATABASE_URL` is unset or unreachable, it raises with a clear message and does not skip.
- Schema: exactly the spec's table, including CHECK constraints, `bookings.inquiry_id` unique FK with `ON DELETE SET NULL`, the partial unique index `uq_bookings_confirmed_date` (on `date` WHERE `status = 'Confirmed'`), unique `blocks.date`, and unique `admins.email`. Money columns are `Numeric(14, 2)`.

- [ ] **Step 1: Create the databases and env lines**

Run, with `PGPASSWORD` taken from the user's message in the shell environment only: `psql -h localhost -U postgres -c "CREATE DATABASE fipconnect"`, then the same command for `fipconnect_test`.

Append to `.env`:
- `DATABASE_URL=postgresql+psycopg://postgres:<pw>@localhost:5432/fipconnect`
- `TEST_DATABASE_URL=postgresql+psycopg://postgres:<pw>@localhost:5432/fipconnect_test`

Add the requirements lines and run `pip install -r requirements.txt`.
Expected: both `CREATE DATABASE` succeed, and pip installs the three packages.

- [ ] **Step 2: Write failing tests**

`tests/test_models.py` (subclass of `DatabaseTestCase`):
- `test_inquiry_to_dict_matches_api_shape`: with budget `Decimal("90000.50")`, guests 780, and a UTC `created_at`, `to_dict()` has exactly the 15 keys:
  `id, reference, name, email, phone, eventName, eventDate, venue, guests, budget, service, notes, status, createdAt, termsAccepted`.
  `budget` is the float `90000.5`, `eventDate` is `"2027-11-16"`, and `createdAt` ends with `"+00:00"`.
- `test_booking_to_dict_matches_api_shape`:
  - keys are `id, inquiryId, clientName, eventName, date, venue, status, expectedRevenue, actualRevenue`;
  - `expectedRevenue` is a float, and `actualRevenue` is `None` when unset.
- `test_service_block_landing_admin_to_dict`: the shapes are
  - service: `id, name, description, active`;
  - block: `id, date, reason`;
  - landing: `organizer, headline, intro`;
  - admin: `{"username": email}`.
- `test_two_confirmed_bookings_on_one_date_are_rejected`: inserting a second Confirmed booking on the same date raises `IntegrityError`. A Cancelled one on that date is allowed.
- `test_block_dates_are_unique` raises `IntegrityError`.
- `test_invalid_inquiry_status_is_rejected` raises `IntegrityError` (via the CHECK constraint).
- `test_seed_defaults_creates_three_services_and_landing`: services come back ordered by `position`, with ids `svc-wedding`, `svc-corporate`, `svc-social`.
- `test_database_url_normalizes_render_scheme`: `postgres://u:p@h/d` and `postgresql://u:p@h/d` both become `postgresql+psycopg://u:p@h/d`. Empty input raises `RuntimeError`.

`tests/test_migrations.py`:
- `test_migration_matches_models`: on the test DB,
  1. drop everything, including `alembic_version`;
  2. run `flask_migrate.upgrade()` inside the app context;
  3. compare against the models with `alembic.autogenerate.compare_metadata(MigrationContext.configure(conn), db.metadata)` and expect `[]`;
  4. check that the seeded services and landing equal `seed_defaults` output.

  In `tearDownClass`, drop everything, including `alembic_version`, so other classes rebuild the schema.

- [ ] **Step 3: Run to verify failure**

Run: `python -m unittest tests.test_models tests.test_migrations`
Expected: ImportError / ModuleNotFoundError for `fipconnect`.

- [ ] **Step 4: Implement config, extensions, models, and the minimal factory**

Minimal `create_app(test_config=None)`: load the config, set `SQLALCHEMY_DATABASE_URI` from `database_url(os.environ.get("DATABASE_URL"))` unless `test_config` supplies one, then call `db.init_app` and `migrate.init_app(app, db, directory=ROOT/"migrations")`.

- [ ] **Step 5: Generate and edit the initial migration**

Run `flask --app fipconnect:create_app db init`, then `db migrate -m "initial"`. Rename the revision to `0001_initial.py`, and check that it contains the CHECK constraints and the partial index (add `postgresql_where` by hand if autogenerate missed it). Add `op.bulk_insert` seeds with literal copies of the defaults.

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m unittest tests.test_models tests.test_migrations`
Expected: all PASS. Also run the full suite: the old `tests/test_app.py` still passes (39) because `app.py` is untouched.

---

### Task 2: Services (security, face, notifications, availability, analytics)

**Files:**
- Create: `fipconnect/services/__init__.py`, `security.py`, `face.py`, `notifications.py`, `availability.py`, `analytics.py`
- Create: `tests/test_services.py`

**Interfaces:**
- Consumes: `db`, models (Task 1).
- Produces:
  - `face.py`: these functions move from `app.py` with bodies unchanged: `validate_face_image`, `face_service_token`, `translate_face_service_error`, `face_service_ready`, `ensure_face_service`, `stop_face_service`, `call_face_service`, `extract_face_embedding`, `verify_face_embedding`, `match_face_embedding`, plus the constants `FACE_MODEL` and `LEGACY_FACE_SERVICE_ERRORS`.

    One change: in `ensure_face_service`, when the started process has exited, call `face_service_ready()` once before raising. If it's ready, return.

    New functions: `encrypt_face_embedding(secret_key, embedding) -> str` and `decrypt_face_embedding(secret_key, token) -> list[float]`. They do the same HKDF/Fernet work as today, but take the secret as an argument. `ROOT` refers to the project root (`Path(__file__).resolve().parents[2]`).
  - `notifications.py`: `send_client_email(inquiry: dict, status)`, `send_client_sms(inquiry: dict, status)`, and `notify_client(inquiry: dict, status)`. Bodies are unchanged; they take `inquiry.to_dict()` output and log through `current_app.logger`.
  - `security.py`:
    - unchanged logic: `is_admin_host() -> bool`, decorators `admin_host_only` and `admin_required`, `csrf_token() -> str`, `require_csrf() -> Response | None`, `api_error(message, status=400)`;
    - new: `current_admin() -> Admin | None`, which looks up `session["admin_id"]`.
  - `availability.py`:
    - `unavailable_dates() -> set[str]`: dates of Confirmed bookings plus block dates, as ISO strings.
    - `is_unavailable(d: date) -> bool`.
    - `lock_date(d: date) -> None`: runs `SELECT pg_advisory_xact_lock(:key)` with `key = 7_000_000_000 + int(d.strftime("%Y%m%d"))`.
    - `lock_setup() -> None`: the same call with key `7_000_000_001`.
  - `analytics.py`: `analytics(inquiries: list[dict], bookings: list[dict]) -> dict`. The body is unchanged from `app.py`, but it takes the two lists instead of `state`.

- [ ] **Step 1: Write failing tests** (`tests/test_services.py`, `DatabaseTestCase` where a DB is needed)
- `test_legacy_face_service_errors_are_translated_to_english`: moved from `test_app.py`, same assertions.
- `test_face_template_round_trip`: encrypt `[0.1]*128` with key `"k"`. The token starts with `"gAAAA"`, doesn't contain `"0.1"`, and decrypts back to the same list. Decrypting with key `"other"` raises `RuntimeError`.
- `test_ensure_face_service_reuses_service_started_by_another_worker`:
  - patch `face.face_service_ready` to return `[False, True]` in turn;
  - patch `subprocess.Popen` to return a mock whose `poll()` returns `1`;
  - patch `shutil.which` to return `"node"`;
  - `ensure_face_service("http://127.0.0.1:5018", "t")` returns without raising.
- `test_analytics_groups_by_event_month_and_counts_conversion`: two inquiries in different months, one Approved. `inquiryMonths` has both months with count 1, and `conversionRate` is `100`.
- `test_unavailable_dates_includes_confirmed_bookings_and_blocks_only`: a Confirmed booking, a Cancelled booking, and one block give exactly 2 dates.
- `test_lock_date_runs_inside_transaction`: inside an app context, `lock_date(date(2027,1,1))` followed by `db.session.commit()` raises nothing.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_services`
Expected: ImportError for `fipconnect.services`.

- [ ] **Step 3: Implement the five modules per Interfaces**

- [ ] **Step 4: Run tests**

Run: `python -m unittest discover -s tests`
Expected: all PASS (the old `test_app.py` is still green).

---

### Task 3: Controllers, full app factory, thin `app.py`, ported tests

**Files:**
- Create: `fipconnect/controllers/__init__.py`, `pages.py`, `public.py`, `auth.py`, `admin.py`
- Modify: `fipconnect/__init__.py` (full factory), `app.py` (replaced by the thin entry point)
- Modify: `tests/test_app.py` (ported)

**Interfaces:**
- Consumes: everything from Tasks 1–2.
- Produces:
  - `fipconnect.create_app(test_config=None) -> Flask`. It does, in order:
    1. sets the secret key the same way as today (`FIPCONNECT_SECRET_KEY`, else `load_or_create_secret()`, moved to `config.py`);
    2. sets the same config keys as today (`ADMIN_HOST`, `ADMIN_HOST_LOCAL_ONLY`, `CLIENT_URL`, `ALLOW_SETUP`, `FACE_SERVICE_URL`, the session cookie flags, `MAX_CONTENT_LENGTH`) plus the DB URI, then applies `test_config`;
    3. calls `db.init_app` and `migrate.init_app`;
    4. registers the four blueprints, the loopback-redirect `before_request` (unchanged), and an `errorhandler(sqlalchemy.exc.OperationalError)` that returns the 500 JSON;
    5. keeps an `errorhandler(RuntimeError)` returning `api_error(str(error), 500)`;
    6. calls `register_cli(app)` from Task 4. Until Task 4 exists, use a no-op stub in `fipconnect/cli.py`.
  - The blueprints have no `url_prefix`, so every route keeps today's path and methods. Each handler validates the same way, with the same messages, as `app.py`. Each one uses models and services and ends with `db.session.commit()`.
  - Date-claiming handlers (`create_inquiry`, an `update_inquiry` approval, `create_block`) call `lock_date(d)` before their availability check. `setup_admin` calls `lock_setup()` before its "no admins" check.
  - `create_inquiry` retries reference generation: on `IntegrityError` from `uq` on `reference`, it rolls back, regenerates, and tries again, up to 5 times.
  - The session stores `session["admin_id"] = admin.id`.
  - `app.py`: `from fipconnect import create_app`, `from fipconnect.config import load_env_file, ROOT`. It calls `load_env_file(ROOT / ".env")`, then `app = create_app()`, and under `__main__` runs `app.run(debug=os.environ.get("FLASK_DEBUG") == "1")`.

- [ ] **Step 1: Port `tests/test_app.py` and add the new tests**

Port the existing tests:
- `FIPConnectAppTests` subclasses `DatabaseTestCase` and builds its app with `self.make_app(TESTING=True, SECRET_KEY="test-only-secret", ALLOW_SETUP=True)`.
- Replace `import app as fip_app`: patch targets become `fipconnect.services.face.extract_face_embedding` / `match_face_embedding`, and `FACE_MODEL` comes from `fipconnect.services.face`.
- Replace JSON-file reads and writes with model queries. For example, "stored face model = Facenet512" becomes `Admin.query.one().face_model = "Facenet512"; db.session.commit()`, and "faceEmbedding startswith gAAAA" becomes a query on `Admin`.
- Tests that called `fip_app.create_app({...})` call `self.make_app(...)`.
- `test_env_file_loader_*` move to `fipconnect.config.load_env_file`.
- `test_legacy_face_service_errors_*` is removed (it moved to `test_services.py`).
- `test_existing_single_admin_data_is_migrated_for_login` is removed (it is replaced in Task 4).

Every other assertion stays byte-for-byte the same.

New tests:
- `test_second_approval_on_same_date_is_refused_without_partial_rows`: submit two inquiries for the same date, then approve the first (200) and the second (409, with the message "This date is already booked or unavailable."). Exactly 1 `Booking` row exists, and the second inquiry's status is still `"Submitted"`.
- `test_blocking_a_booked_date_is_refused`: approve an inquiry, then `POST /api/blocks` for its date returns 409 "That date is already unavailable." `Block.query.count() == 0`.
- `test_admin_data_money_fields_are_numbers`: after the approval, `type(data["bookings"][0]["expectedRevenue"]) is float` and `type(data["inquiries"][0]["budget"]) in (float, type(None))`.
- `test_database_unavailable_returns_json_500`: `make_app(SQLALCHEMY_DATABASE_URI="postgresql+psycopg://postgres:x@127.0.0.1:1/none", ...)`, then `GET /api/bootstrap` returns 500 with `get_json() == {"error": "The database is unavailable. Please try again shortly."}`.
- `test_session_survives_across_requests_with_admin_id`: after `setup_admin`, `GET /api/admin/data` returns `admin.username == "admin@example.com"`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_app`
Expected: the ported tests fail because `fipconnect.create_app` has no routes (404s).

- [ ] **Step 3: Implement the controllers, the full factory, and the thin `app.py`**

- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover -s tests`
Expected: all PASS.

---

### Task 4: JSON import, local data move, docs

**Files:**
- Create: `fipconnect/cli.py` (replaces the stub), `tests/test_import.py`
- Modify: `README.md`, `.env.example`

**Interfaces:**
- Consumes: models and `seed_defaults` (Task 1), `create_app` (Task 3).
- Produces:
  - `register_cli(app)` adds the `import-json` command with an optional `PATH` argument (default `ROOT/"instance"/"fipconnect.json"`).
  - The command delegates to `import_json(path: Path) -> dict[str, int]`, which returns counts `{"admins", "inquiries", "bookings", "blocks", "services"}`.
  - `import_json` raises `ImportRefused(message)` when the data can't be imported, and the command prints the message and exits 1.

- [ ] **Step 1: Write failing tests** (`tests/test_import.py`, `DatabaseTestCase`; each test writes a JSON file to a temp dir)
- `test_import_copies_records_with_original_ids`:
  - the file has 1 admin (hash from `generate_password_hash("pw-123456")`, face token from `encrypt_face_embedding("test-only-secret", [0.1]*128)`), 2 inquiries, 1 Confirmed booking linked to the first inquiry, 1 block, 2 services, and a custom landing;
  - the counts are `{"admins":1,"inquiries":2,"bookings":1,"blocks":1,"services":2}`;
  - `Inquiry.query.get(<id>).reference` is unchanged, `Service.query.count() == 2` (the seeds were replaced), and the landing equals the file's.
- `test_imported_admin_can_sign_in_with_password_and_face`:
  - after the import, `POST /api/login` on the admin host returns 200;
  - log out, then call `/api/login/face` with only `match_face_embedding` patched to return 0. The real decrypt runs, and the response is 200.
- `test_import_accepts_legacy_single_admin_key`: a file with `"admin": {...}` and no `"admins"` imports 1 admin.
- `test_import_refuses_when_database_has_data`: import once, then a second import raises `ImportRefused` whose message contains `"already has data"`.
- `test_import_aborts_whole_file_on_bad_record`: a file whose inquiry has status `"Bogus"` raises `ImportRefused` containing that inquiry's id, and `Admin.query.count() == 0` afterwards.
- `test_cli_reports_counts`: `app.test_cli_runner().invoke(args=["import-json", str(path)])` exits with 0, and its output contains `"Imported 1 admins, 2 inquiries"`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_import`
Expected: ImportError for `import_json`.

- [ ] **Step 3: Implement `fipconnect/cli.py`**

Use one transaction. Map camelCase to the model fields. Money goes through `Decimal(str(value)).quantize(Decimal("0.01"))`. Service `position` follows file order. Admins get `created_at = now(UTC)`. Any `IntegrityError` or invalid value raises `ImportRefused` naming the record id.

- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover -s tests`
Expected: all PASS.

- [ ] **Step 5: Move the real data**

Run `flask --app app db upgrade`, then `flask --app app import-json`.
Expected: the upgrade finishes with no errors, and the import prints `Imported 1 admins, 2 inquiries, 0 bookings, 0 blocks, 3 services`.

Then start `python -c "import app; app.app.run(port=5055)"`, check that `GET http://localhost:5055/api/bootstrap` returns 3 services, and stop the server.

- [ ] **Step 6: Docs**

README:
- Replace the JSON-storage paragraphs with PostgreSQL setup. The steps are: install requirements, create the `fipconnect` and `fipconnect_test` databases, set `DATABASE_URL` / `TEST_DATABASE_URL` in `.env`, run `flask --app app db upgrade`, then optionally `flask --app app import-json`.
- Add the new `fipconnect/` layout to the project tree.
- Add a "Schema changes" note: `flask --app app db migrate -m "..."`, then `db upgrade`.
- Render section:
  - add a Render PostgreSQL database and set `DATABASE_URL` to its internal URL;
  - Build Command: `pip install -r requirements.txt && npm install && flask --app app db upgrade`;
  - Start Command: `gunicorn --workers 2 --threads 4 --bind 0.0.0.0:$PORT app:app`;
  - the disk is no longer needed;
  - to move local data, set Render's `FIPCONNECT_SECRET_KEY` to the local `instance/secret.key` contents, then run `import-json` locally with `DATABASE_URL` set to the external URL.
- Remove `FIPCONNECT_DATA_FILE` mentions.

`.env.example`: add `DATABASE_URL=postgresql+psycopg://postgres:your-password@localhost:5432/fipconnect` and `TEST_DATABASE_URL=...fipconnect_test` placeholders.
