# Face check before adding admins or re-enrolling — short design

Date: 2026-11-22 · Size: small-to-medium change (short design)

## Intent
Stop someone who has stolen an admin's password from (a) adding a fake admin and
(b) replacing the account's face with their own via Re-enroll face. Before either
action, the signed-in admin must prove it's them with a live face scan matched
against their saved face.

## Goals / non-goals
- Goal: Add admin and Re-enroll face require a fresh "it's you" face check.
- Goal: accounts whose saved face is from the old model (can't be face-checked)
  confirm with their password instead, once, to re-enroll.
- Non-goal: ID capture (option B, not chosen), liveness/anti-spoofing, changes to
  first-time setup, password or face login.
- Anti-goal: a stolen password alone can add an admin or change a face.

## Approaches
- **A. Face check on the person doing it (chosen).** Reuses the existing face
  match; no new personal data.
- B. ID capture + ID-to-face match for the new admin — doesn't stop the threat alone.
- C. A + B — most work, adds ID privacy decisions.

## Design
- **Check:** `POST /api/admin/verify-face` (admin host, signed in, CSRF header):
  takes a live photo, compares it with **the signed-in admin's own** saved face
  (existing verify, same 0.6 threshold). On a match, the session records
  `step_up_at` (time). On no match: 401 "Face not recognized. Please try again."
- **Password fallback:** `POST /api/admin/verify-password` with the account
  password, allowed **only** when the account has no usable face template (missing
  or old model); otherwise 403. On success it sets the same `step_up_at`.
- **Freshness:** a check is valid for **5 minutes** and is **used up** by the action
  it allows. `POST /api/register-admin` and `POST /api/admin/face` refuse without a
  fresh check: 403 "Confirm it's you first." (the new admin's own scan works as
  today).
- **Pages:** `/admins/new` and `/account/face` show step 1 "Confirm it's you" (a
  face scan button, or a password field for old-model accounts). After it passes,
  the page reloads showing step 2 (today's form/scan), with a note of how long the
  confirmation lasts. A short expiry message appears if step 2 is attempted late.
- **Wrong person blocked:** the check only compares against the signed-in admin's
  template — another admin's face does not count.
- **Known limit (documented):** face matching has no liveness check, so a good
  photo of the real admin could pass; the password is still required to sign in.

## Tests
Endpoint rules (match/no-match/expiry/used-up/fallback only for old-model
accounts/CSRF/admin host only), register-admin and admin/face refused without a
fresh check and allowed with one, pages show step 1 then step 2.

## Left to the builder
Exact wording, how the remaining time is shown, helper names.
