# Face scan as a required second step at sign-in — short design

Date: 2026-11-25 · Size: small-to-medium change (short design)

## Intent
A stolen admin password alone must not be enough to sign in. After the password
is accepted, the admin must pass a live face scan matched against **their own**
saved face before they are signed in.

## Goals / non-goals / anti-goals
- Goal: every password sign-in needs a face match against that account's face.
- Goal: accounts with no usable saved face (none, or old model) can still get in
  once, and are forced to enroll a face before doing anything else.
- Non-goal: liveness / anti-spoofing, email codes, changes to first-time setup,
  the "Confirm it's you" step before adding admins / re-enrolling.
- Anti-goal: any path that signs someone in with only a password (except the
  one-time no-face enrollment below) or with only a face.

## Approaches
- **A. Password first, then face match on that account (chosen).** Reuses the
  existing face verify and lockout rules.
- B. Keep face-only sign-in alongside it — rejected: a photo of an admin would
  get in without the password (no liveness check).
- C. Face first, then password — same protection, worse: matches against all
  admins and keeps a face-only path.

No-face accounts — options considered: password then forced re-enroll (**chosen**
by the user), another admin approves, email code, fully locked out.

## Design
- **Password step:** `POST /login` with a correct password no longer calls
  `sign_in`. It clears the session and stores `pending_admin_id` + `pending_at`
  (time). `current_admin()` ignores the pending id, so no admin page or API
  works. Redirects to `/login/face`.
- **Face step:** `GET /login/face` shows the camera ("One more step: scan your
  face"), plus "Start over" (back to `/login`, clears pending). The scan posts to
  `POST /api/login/face` (CSRF as today), which now compares the photo **only**
  with the pending admin's own template (`face.verify_face_embedding`, same
  threshold). Match → `sign_in(admin)` (clears pending), go to `/`.
  No match → 401 "Face not recognized. Please try again."
- **Pending expiry:** the pending state lasts **5 minutes**; after that the face
  step refuses and sends them back to `/login` with "Sign-in timed out. Enter
  your password again."
- **Attempt limit:** wrong face scans count toward the existing
  `step_up_failures`; 5 → locked 15 min (`step_up_locked_until`). While locked,
  the face step refuses with the remaining time; the password step still
  accepts the password but the face step stays locked.
- **No usable face (none saved or old model):** after a correct password, the
  admin is signed in in a **restricted "enroll only" mode** (session flag
  `must_enroll_face`). Every admin page redirects to `/account/face`, and every
  admin API except enrolling the face (`POST /api/admin/face`) and logout
  returns 403 "Enroll your face first." Enrolling in this mode needs no
  "Confirm it's you" step. Once a face is saved, the flag is cleared and they
  are fully signed in.
- **Remove** the "Sign in with facial recognition" button and the face-only
  any-admin matching from the sign-in page.
- **Login page text:** "Sign in with your email and password. You'll then scan
  your face."

## Known limit (documented)
- During the one-time no-face enrollment, someone with a stolen password could
  enroll their own face. Accepted by the user for convenience. Accounts that
  already have a usable face are not affected.
- Face matching still has no liveness check; a photo plus the password could pass.

## Tests
Correct password → not signed in, redirected to face step; admin pages/APIs
refuse a pending session; face match on own template signs in; another admin's
face does not; expiry after 5 min; 5 failures lock; no-face account gets
enroll-only mode, everything else 403/redirect, enrolling clears it; face-only
sign-in button gone and `/api/login/face` without a pending password refuses.

## Left to the builder
Exact wording, helper names, whether pending state reuses `step_up` helpers.
