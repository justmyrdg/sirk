# Face Scan as Required Second Sign-in Step Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A correct password no longer signs an admin in; they must then pass a face scan matched against their own saved face. Accounts with no usable face get a restricted "enroll only" sign-in.

**Architecture:** The password step stores a short-lived *pending* sign-in in the Flask session (no `admin_id`, so every existing guard treats it as signed out). `/login/face` + `POST /api/login/face` complete it by matching the photo against only the pending admin's template. No-usable-face accounts get `sign_in(admin, enroll_only=True)`, and the two admin guards refuse every view not marked as allowed in that mode.

**Tech Stack:** Flask, SQLAlchemy (Postgres), Jinja templates, vanilla JS (`admin_static/admin.js`), unittest (`python -m unittest discover -s tests`).

**Spec:** `docs/superpowers/specs/2026-11-25-face-login-second-step-design.md`

## Global Constraints

- Pending sign-in lasts **5 minutes** (`PENDING_WINDOW = 300` seconds).
- Wrong face scans at sign-in use the existing counters: **5 failures → locked 15 min** (`step_up.record_failure`, `step_up.locked_seconds`, existing `locked_response` → 429).
- Face match: `face.verify_face_embedding(image, own_embedding, FACE_SERVICE_URL, face_service_token(secret))`, against **only** the pending admin's template.
- A successful sign-in face scan must **not** count as a "Confirm it's you" check (do not call `step_up.mark_verified`).
- Copy: no match → `"Face not recognized. Please try again."`; expired → `"Sign-in timed out. Enter your password again."`; enroll-only refusal → `"Enroll your face first."`; login page intro → `"Sign in with your email and password. You'll then scan your face."`
- The "Sign in with facial recognition" button and face-only any-admin matching are removed.
- First-time setup (`/api/setup-admin`) still signs in fully, unchanged.
- Existing "Confirm it's you" flows (`verify-face`, `verify-password`, `allow-face-reset`) are unchanged for fully signed-in admins.

## Review Focus

1. Face service down / bad photo at the face step → 503/400 with the service message, and the pending sign-in stays usable for a retry (no lockout count).
2. Admin deleted (or face removed) between password and face step → face step returns 401 "Sign-in timed out. Enter your password again.", not a 500.
3. A pending session (password OK, no face yet) calling any admin API or page → treated as signed out (401 / redirect to `/login`).
4. Enroll-only admin calling a sensitive API (`/api/register-admin`) → 403 "Enroll your face first.", and a failed enrollment (extraction error) keeps them in enroll-only mode.
5. Already fully signed-in admin opening `/login/face` → redirect to `/`; no pending → redirect to `/login?expired=1`.

Each has a test in the owning task below.

---

### Task 1: Password → pending → face step

**Files:**
- Modify: `fipconnect/services/security.py` (pending helpers)
- Modify: `fipconnect/services/step_up.py` (add `clear_failures`)
- Modify: `fipconnect/controllers/admin_pages.py:37-47` (`login_submit`), add `GET /login/face`, `GET /login` reads `?expired=1`
- Modify: `fipconnect/controllers/auth.py:144-185` (`login_face` rewritten)
- Create: `templates/admin/login_face.html`
- Modify: `templates/admin/login.html` (remove face button + camera include, new intro copy, expired notice)
- Modify (existing tests that sign in by form or face-only): `tests/test_admin_auth_pages.py`, `tests/test_app.py`, `tests/test_import.py`
- Test: `tests/test_face_login.py` (new)

**Interfaces:**
- Produces (in `security.py`):
  - `PENDING_WINDOW = 300`
  - `begin_pending(admin) -> str` — `session.clear()`, sets `pending_admin_id` (int) and `pending_at` (float, `time.time()`), returns `csrf_token()`.
  - `pending_admin() -> Admin | None` — the pending admin if set, not older than `PENDING_WINDOW`, and the row still exists; else `None`.
  - `sign_in(admin)` unchanged in this task (clears pending as a side effect of `session.clear()`).
- Produces (in `step_up.py`): `clear_failures(admin) -> None` — zeroes `step_up_failures`, clears `step_up_locked_until`, commits. Does not touch the session.
- Behaviour of `login_submit`: if `step_up.has_usable_face(admin)` → `begin_pending(admin)`, 303 to `/login/face`; else → `sign_in(admin)`, 303 to `/` (today's behaviour; Task 2 restricts it).
- `POST /api/login/face` (admin host, CSRF): no/expired pending → 401 `"Sign-in timed out. Enter your password again."`; locked → existing `locked_response`; no usable face on pending admin → 401 same timed-out message; ValueError → 400, RuntimeError → 503 (pending kept, no failure counted); no match → `record_failure`, 401 `"Face not recognized. Please try again."`; match → `clear_failures`, `sign_in(admin)`, `{"ok": true, "csrfToken": ...}`.
- `GET /login/face`: fully signed in → 303 `/`; no `pending_admin()` → 303 `/login?expired=1`; else render `login_face.html` with a `data-flow="login" data-next="/"` button, the camera partial, and a "Start over" link to `/login`.

- [ ] **Step 1: Write the failing tests in `tests/test_face_login.py`**

Class `FaceLoginTests(DatabaseTestCase)`; setUp creates the admin via `/api/setup-admin` (as in `tests/test_step_up.py:16-25`), then `POST /logout`. Helper `password_login()` fetches `/login`, scrapes the form `csrf_token`, posts the password. Helper `face_step(result=True)` fetches `/login/face`, reads the `<meta name="csrf-token">`, posts `/api/login/face` with `verify_face_embedding` patched to `result`.

```python
def test_password_alone_does_not_sign_in(self):
    response = self.password_login()
    self.assertEqual(response.status_code, 303)
    self.assertTrue(response.headers["Location"].endswith("/login/face"))
    self.assertTrue(self.get("/").headers["Location"].endswith("/login"))      # pages: signed out
    self.assertEqual(self.api("/api/admin/verify-face", faceImage=PHOTO).status_code, 401)  # Review Focus 3: @admin_required API sees signed out

def test_face_match_completes_sign_in(self):
    self.password_login()
    response, verify = self.face_step(True)
    self.assertEqual(response.status_code, 200)
    self.assertEqual(verify.call_args.args[1], [0.1] * 128)   # own template only
    self.assertEqual(self.get("/").status_code, 200)

def test_face_mismatch_refused(self):
    self.password_login()
    response, _ = self.face_step(False)
    self.assertEqual(response.status_code, 401)
    self.assertEqual(response.get_json()["error"], "Face not recognized. Please try again.")
    self.assertTrue(self.get("/").headers["Location"].endswith("/login"))

def test_other_admins_face_is_not_used(self):
    # add a second admin row directly with embedding [0.9]*128; sign in as the first
    # assert verify called exactly once, with [0.1]*128

def test_pending_expires_after_five_minutes(self):
    with patch.object(security, "now", return_value=1000.0): self.password_login()
    with patch.object(security, "now", return_value=1301.0):
        response, _ = self.face_step(True)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "Sign-in timed out. Enter your password again.")
        page = self.get("/login/face")
        self.assertTrue(page.headers["Location"].endswith("/login?expired=1"))

def test_face_step_without_password_refused(self):          # fresh client, no pending
    # /api/login/face → 401 timed-out message; verify_face_embedding not called

def test_face_step_locks_after_five_failures(self):
    # 5 × face_step(False) → 5th is 401; 6th → 429; after patching step_up.now +15min+1 → match → 200

def test_success_clears_failures_and_is_not_a_step_up(self):
    # 2 failures then success → admin.step_up_failures == 0;
    # POST /api/register-admin right after → 403 "Confirm it's you first."

def test_face_service_error_keeps_pending(self):             # Review Focus 1
    # verify_face_embedding side_effect RuntimeError("down") → 503; then True → 200; step_up_failures == 0

def test_admin_deleted_between_steps(self):                  # Review Focus 2
    # password_login, delete the admin row, face_step → 401 timed-out message

def test_login_face_page_redirects(self):                    # Review Focus 5
    # no pending → /login?expired=1 ; fully signed in → /

def test_login_page_has_no_face_only_button(self):
    html = self.get("/login").get_data(as_text=True)
    self.assertNotIn('data-flow="login"', html)
    self.assertIn("You'll then scan your face.", html)
    self.assertIn("Sign-in timed out", self.get("/login?expired=1").get_data(as_text=True))
```

`security.now()` is a new module-level `def now(): return time.time()` used by `begin_pending`/`pending_admin` so tests can patch it (same pattern as `step_up.now`).

- [ ] **Step 2: Run to verify they fail**

Run: `python -m unittest tests.test_face_login -v`
Expected: FAIL (password login redirects to `/`, `/login/face` 404, `security.now` missing).

- [ ] **Step 3: Implement** the Interfaces above in `security.py`, `step_up.py`, `admin_pages.py`, `auth.py`, and the two templates. `login_face` follows `verify_own_face` (`auth.py:219-252`) for decrypt → `db.session.rollback()` → verify → re-fetch admin; `login_face.html` extends `admin/base.html` like `login.html`, heading "One more step", text "Scan your face to finish signing in."

- [ ] **Step 4: Update existing tests that relied on the old sign-in**

- `tests/test_admin_auth_pages.py`: `login()` helper completes the face step (patch `face.verify_face_embedding` → True); line ~104 assert the face-only button is gone instead of present; keep line ~117 (`/api/login/face` still in `admin.js`).
- `tests/test_app.py`: `form_login()` completes the face step for accounts with a usable face; rewrite the face-only cases at ~130, ~217, ~327, ~342 to the new rules (no pending → 401). The legacy-model test at ~123 keeps passing because no-face accounts still sign in fully in this task.
- `tests/test_import.py:~122-134`: after the password post, call `/api/login/face` with the pending session and assert 200.

- [ ] **Step 5: Run the whole suite**

Run: `python -m unittest discover -s tests`
Expected: OK, no failures.

- [ ] **Step 6: Commit**

```bash
git add fipconnect templates tests
git commit -m "Require a face scan after the password to sign in"
```

---

### Task 2: Enroll-only sign-in for accounts without a usable face

**Files:**
- Modify: `fipconnect/services/security.py` (`sign_in`, `admin_required`, `page_admin_required`, new `enroll_only_ok`, `is_enroll_only`)
- Modify: `fipconnect/controllers/admin_pages.py` (`login_submit` branch, `face_enroll` view + context)
- Modify: `fipconnect/controllers/auth.py:188-214` (`update_admin_face`)
- Modify: `templates/admin/face_enroll.html`
- Test: `tests/test_face_login.py` (add `EnrollOnlyTests`), `tests/test_app.py:~123` (legacy re-enroll test)

**Interfaces:**
- Consumes: Task 1's `login_submit` branch, `security.now`, `step_up.has_usable_face`.
- Produces:
  - `sign_in(admin, enroll_only=False) -> str` — as today; when `enroll_only`, also `session["must_enroll_face"] = True`.
  - `is_enroll_only() -> bool` — `session.get("must_enroll_face") is True`.
  - `enroll_only_ok(view)` — decorator that sets `view.enroll_only_ok = True`; apply it **inside** (below) `@admin_required` / `@page_admin_required`, and the guards read it with `getattr(view, "enroll_only_ok", False)`.
  - `admin_required`: if signed in and `is_enroll_only()` and view not marked → `api_error("Enroll your face first.", 403)`.
  - `page_admin_required`: same condition → 303 to `/account/face`.
  - Marked views: `GET /account/face`, `POST /api/admin/face`. (`/logout` and `/api/admin/bootstrap` use host-only guards and already work.)
- `login_submit`: no usable face → `sign_in(admin, enroll_only=True)`, 303 to `/account/face`.
- `update_admin_face`: when `is_enroll_only()`, skip the `step_up.is_fresh` / `step_up.consume` checks; after a successful save, `session.pop("must_enroll_face")`. Otherwise unchanged.
- `face_enroll.html`: when `enroll_only` (context var), show heading "Enroll your face", text "Your account has no face we can check. Scan your face to finish signing in.", and the scan button directly (`data-flow="reenroll" data-next="/"`), with no step 1.

- [ ] **Step 1: Write the failing tests (`EnrollOnlyTests` in `tests/test_face_login.py`)**

setUp: setup admin, set `face_model = "old-model"` on the row (as `tests/test_step_up.py:99` `set_old_model`), log out.

```python
def test_no_face_account_gets_enroll_only(self):
    response = self.password_login()
    self.assertTrue(response.headers["Location"].endswith("/account/face"))
    self.assertTrue(self.get("/").headers["Location"].endswith("/account/face"))
    self.assertIn("Enroll your face", self.get("/account/face").get_data(as_text=True))

def test_enroll_only_blocks_other_apis(self):                # Review Focus 4
    r = self.api("/api/register-admin", email="x@example.com", password="pw-123456789", faceImage=PHOTO)
    self.assertEqual(r.status_code, 403)
    self.assertEqual(r.get_json()["error"], "Enroll your face first.")

def test_enrolling_needs_no_step_up_and_lifts_restriction(self):
    # extract_face_embedding → [0.3]*128; POST /api/admin/face → 200;
    # row.face_model == face.FACE_MODEL; GET / → 200

def test_failed_enrollment_keeps_restriction(self):          # Review Focus 4
    # extract_face_embedding side_effect ValueError("No face") → 400; GET / still → /account/face

def test_enroll_only_logout_works(self):
    # POST /logout → /login; GET /account/face → /login
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m unittest tests.test_face_login.EnrollOnlyTests -v`
Expected: FAIL (password login lands on `/`, register-admin returns "Confirm it's you first.").

- [ ] **Step 3: Implement** the Interfaces above.

- [ ] **Step 4: Update `tests/test_app.py:~123`** (`test_admin_can_reenroll_face_after_password_login`): after the password login it is now in enroll-only mode, so re-enrolling succeeds without a "Confirm it's you" step; remove the old face-only 409 assertion (that endpoint now needs a pending sign-in).

- [ ] **Step 5: Run the whole suite**

Run: `python -m unittest discover -s tests`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add fipconnect templates tests
git commit -m "Accounts without a usable face must enroll one right after signing in"
```
