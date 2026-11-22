# SDD ledger — plan: docs/superpowers/plans/2026-11-22-server-rendered-views.md
Setup: no git; backups at C:/Users/Justmyr/AppData/Local/Temp/claude/4a0986ef1abc587e/7593429c-f29d-4f3a-a706-25ed556a1438/scratchpad/backup-before-views
Pre-flight: T2-T5 consume T1 services; T3-T5 consume T2 foundation; T5 consumes T4 layout/page_admin_required — consistent
Task 1: Ruling: JSON PUT /api/services with name AND active now commits the name before checking active's type (was all-or-nothing) — only reachable by hand-made requests, and this JSON route is removed in Task 5 — cost if wrong: none after Task 5
Task 1: complete (tests: python -m unittest discover -s tests → Ran 79, OK)
Task 2: Ruling: plan's partials/form_errors.html became partials/notices.html (one macro for flashed + page errors) and added a month_short filter for analytics bars — same purpose, fewer files — cost if wrong: none
Task 2: Ruling: unknown pages now render an HTML 404 page (JSON under /api/) — needed for the page site; tested — cost if wrong: none
Task 2: complete (tests: python -m unittest discover -s tests → Ran 87, OK, expected failures=1 (Task 3 removes))
Task 3: Ruling: test helper submit_inquiry now calls the inquiries service directly (returns the reference) instead of posting — keeps admin-side tests focused; the form path has its own tests in test_client_pages.py — cost if wrong: none
Task 3: Ruling: calendar days are links/spans instead of buttons; added a.calendar-day hover + no-underline CSS — needed for no-JS links — cost if wrong: cosmetic
Task 3: Ruling: the thank-you page also shows the first name (as the old JS did), passed with the code via flash — cost if wrong: none
Task 3: complete (tests: python -m unittest discover -s tests → Ran 93, OK)
Task 4: Ruling: after add-admin / re-enroll succeed, the camera script goes to the same page with ?added=1 / ?updated=1 which shows the success notice (JSON endpoints can't flash) — cost if wrong: none
Task 4: Ruling: removed 3 old tests that read the SPA script for add-admin/setupAllowed strings; the same features are covered by test_admin_auth_pages (setup-off page text, register flow page, admin.js endpoints) — cost if wrong: none
Task 4: Ruling: added a small .inline-logout CSS rule so the Log out button (now a POST form) sits inline in the header — cost if wrong: cosmetic
Task 4: complete (tests: python -m unittest discover -s tests → Ran 99, OK)
Task 5: Ruling: workspace routes live in a new controllers/workspace_pages.py instead of growing admin_pages.py — one file per area — cost if wrong: none
Task 5: Ruling: review page hint now says the client is notified by email/SMS when those are set up (old text "not contacted automatically" was wrong since notifications exist) — cost if wrong: copy only
Task 5: Ruling: bookings tables show Expected and Actual revenue columns (needed to show ₱ amounts that used to be only in the modal) — cost if wrong: cosmetic
Task 5: Ruling: retired 8 JSON-workspace tests; each behavior is covered by tests/test_admin_pages.py + tests/test_domain.py; ported the concurrent-change test to the page (passed first run because the handler predates it)
Task 5: Ruling: Chrome extension not connected — browser check done with curl against the live server (client pages, forms, guards) + test-client render of every signed-in admin page against the real DB; visual layout NOT checked in a real browser — cost if wrong: a layout glitch the user sees first
Task 5: complete (tests: python -m unittest discover -s tests → Ran 108, OK)
Final review: fresh reviewer (opus) — no critical
Final: fixed extreme ?month= (9999-12, 0001-01) gave 500 — test_availability_extreme_months_fall_back / test_schedule_extreme_months_fall_back / test_month_from_param_falls_back RED→GREEN, suite 111/111
Final: fixed (re-graded Minor→Important) Log out with an outdated token left the admin signed in silently — test_logout_with_stale_token_still_signs_out RED→GREEN, suite 111/111
Final: minor (deferred): camera flows no longer retry once with a fresh token after "session expired" (user must retype and rescan)
Final: minor (deferred): "Active" service label is now green (was gray)
Final: minor (deferred): client nav has no aria-current on the current page
Final: minor (deferred): "Mark complete" button no longer on the Analytics revenue table (still on Schedule)
Final: minor (deferred): 405/400/413 errors show Flask's plain page instead of the site's error page
Final: minor (deferred): README tree doesn't list the new service modules
