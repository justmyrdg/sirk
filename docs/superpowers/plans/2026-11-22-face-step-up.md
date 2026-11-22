# Face Step-up Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require the signed-in admin to pass a fresh "it's you" check (a live face match against their own saved face, or their password if their saved face is unusable) before Add admin or Re-enroll face.

**Architecture:**
- A small `fipconnect/services/step_up.py` keeps a timestamp in the session.
- Two new JSON endpoints in `controllers/auth.py` set it: `verify-face` and `verify-password`.
- `register-admin` and `admin/face` require it and use it up on success.
- The two pages render step 1 or step 2 based on it.
- `admin.js` gets a `verify` flow and a password form.

**Tech Stack:** Flask, the existing face service (`face.verify_face_embedding`), unittest.

**Spec:** `docs/superpowers/specs/2026-11-22-face-step-up-design.md`

**Note:** No git. Back up `fipconnect/`, `templates/`, `admin_static/` and `tests/` first. Test command: `python -m unittest discover -s tests`.

## Global Constraints
- **Freshness:** 300 seconds. The check is used up only when the action succeeds, so a failed photo doesn't burn it.
- **Messages:**
  - no match: 401 "Face not recognized. Please try again."
  - action without a fresh check: 403 "Confirm it's you first."
  - wrong password: 401 "Incorrect password."
  - password fallback on an account with a usable face: 403 "Use a face scan to confirm it's you."
- **Comparison:** only ever against the signed-in admin's own template (`face_model == FACE_MODEL` and an embedding present = "usable").
- **Unchanged:** first-time setup, `/login`, `/api/login/face`.
- **Scope:** all new endpoints are admin host only, signed in, and checked with the CSRF header.

## Review Focus
1. **Another admin's face must not count:** with two admins, admin B's photo while signed in as A gives 401. Test: Task 1 `test_verify_face_compares_only_own_template` (it asserts the embedding passed to verify is A's).
2. **Expired check:** after 301 seconds, register is refused with 403. Test: Task 1 `test_check_expires_after_five_minutes` (patch `step_up.now`).
3. **Use-once:** a second register after a successful one gives 403. Test: Task 1 `test_check_is_used_up_by_success`.
4. **A failed action keeps the check:** a bad new-admin photo (400) still allows a retry. Test: Task 1 `test_failed_action_keeps_check`.
5. **Old-model account:** the password fallback works, and face verify returns 409 "Your saved face can't be checked. Confirm with your password." Test: Task 1 `test_old_model_account_uses_password`.

---

### Task 1: Step-up rules and endpoints

**Files:** Create `fipconnect/services/step_up.py` and `tests/test_step_up.py`. Modify `fipconnect/controllers/auth.py`, plus `tests/test_app.py` and `tests/test_admin_auth_pages.py` (tests that call `register-admin` or `admin/face` first call `verify-face` with `face.verify_face_embedding` patched to `True`).

**Interfaces (produces):**
- `step_up.now() -> float`, which wraps `time.time()` so tests can patch it.
- `step_up.mark_verified() -> None`.
- `step_up.seconds_left() -> int`: 0 when there's no check or it has expired.
- `step_up.is_fresh() -> bool`.
- `step_up.use() -> None`, which removes the check.
- `step_up.has_usable_face(admin) -> bool`.
- `step_up.WINDOW = 300`.
- `POST /api/admin/verify-face`:
  - body `{faceImage}`;
  - an old-model account gets 409 "Your saved face can't be checked. Confirm with your password.";
  - otherwise it calls `face.verify_face_embedding(image, own_embedding, url, token)`; `True` gives 200 `{"ok": true, "secondsLeft": 300}`.
- `POST /api/admin/verify-password`: body `{password}`, with the rules in Global Constraints.
- `register_admin` and `update_admin_face`: refuse with 403 unless `is_fresh()` (checked before any face work); call `use()` after commit.

- [ ] **Step 1: Write failing tests** (`tests/test_step_up.py`, admin signed in through the setup endpoint)
- `test_register_admin_requires_fresh_check`: without a check, register gives 403 "Confirm it's you first.", and `extract_face_embedding` isn't called.
- `test_verify_face_then_register`: verify (patched `True`) gives 200, then register gives 200 and 2 admins exist.
- `test_verify_face_rejects_mismatch`: verify patched `False` gives 401 with the message, and register is still 403.
- `test_verify_face_compares_only_own_template`: two admins exist (B added through a verified register), A is signed in, and `verify_face_embedding` is called with A's decrypted embedding (`[0.1]*128`), not B's (`[0.2]*128`).
- `test_check_expires_after_five_minutes`: patch `step_up.now` so verify happens at 1000 and register at 1301, which gives 403.
- `test_check_is_used_up_by_success`: verify, register (200), then register again gives 403.
- `test_failed_action_keeps_check`: verify; register with `extract_face_embedding` raising `ValueError("bad")` gives 400; register again with a good photo gives 200.
- `test_reenroll_requires_fresh_check`: `/api/admin/face` without a check gives 403; with one, 200.
- `test_old_model_account_uses_password`:
  - set A's `face_model = "Facenet512"`;
  - verify-face gives 409;
  - verify-password with a wrong password gives 401 "Incorrect password."; with the right one, 200;
  - then `/api/admin/face` gives 200.
- `test_password_fallback_refused_with_usable_face`: 403 with the message.
- `test_step_up_endpoints_admin_host_and_csrf`: on the client host, 404; without CSRF, 400.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_step_up`
Expected: FAIL.

- [ ] **Step 3: Implement.** Port the existing tests' register and re-enroll calls (add `verify_first()` helpers).

- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover -s tests`
Expected: PASS.

### Task 2: Two-step pages and camera flow

**Files:** Modify `fipconnect/controllers/admin_pages.py` (`new_admin`, `face_enroll`), `templates/admin/admin_new.html`, `templates/admin/face_enroll.html`, and `admin_static/admin.js`. Create `templates/partials/step_up.html`. Add tests to `tests/test_step_up.py`.

**Interfaces:**
- Pages get `step_up_left` (seconds) and `usable_face` (bool).
- When `step_up_left == 0`, the page renders the partial:
  - with a usable face: a button `data-flow="verify" data-next="<this page>"`;
  - otherwise: `<form data-flow="verify-password" data-next="...">` with a password field.
- When `step_up_left > 0`, it renders today's step-2 content plus "Confirmed. You have about N minutes to finish."
- `admin.js`: the `verify` flow (camera → `/api/admin/verify-face`) and the `verify-password` flow (form submit, no camera → `/api/admin/verify-password`), both navigating to `data-next` on success. A 403 "Confirm it's you first." in step 2 shows the message and reloads to step 1 after 2 seconds.

- [ ] **Step 1: Write failing tests**
- `test_add_admin_page_shows_step_one_until_verified`: `/admins/new` has `data-flow="verify"` and doesn't have `data-flow="register"`. After verify, it has `data-flow="register"` and "Confirmed".
- `test_reenroll_page_uses_password_for_old_model`: with face_model `Facenet512`, `/account/face` has `data-flow="verify-password"`.
- `test_admin_js_has_step_up_flows`: the file contains `/api/admin/verify-face` and `/api/admin/verify-password`, and has no `innerHTML`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_step_up`
Expected: FAIL.

- [ ] **Step 3: Implement.** Then run `node --check admin_static/admin.js`.

- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover -s tests`
Expected: PASS. Then update the README's admin paragraph to describe the confirm step and its known limit.
