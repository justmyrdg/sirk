# SDD ledger — plan: docs/superpowers/plans/2026-11-22-face-step-up.md
Setup: no git; backups at C:/Users/Justmyr/AppData/Local/Temp/claude/4a0986ef1abc587e/7593429c-f29d-4f3a-a706-25ed556a1438/scratchpad/backup-before-stepup; execution: native (user's standing choice)
Pre-flight: T2 consumes T1 step_up + endpoints — consistent
Task 1: complete (tests: python -m unittest discover -s tests → 142 pass; only the 3 Task 2 page tests red as planned)
Task 2: complete (tests: python -m unittest discover -s tests → Ran 145, OK)
Final review: fresh reviewer (opus) — no critical
Final: fixed use-once only enforced in the cookie (replayed cookie added a second admin) — server-side step_up_used_at + atomic conditional UPDATE — test_used_up_check_cannot_be_replayed_with_old_cookie RED→GREEN, suite 151/151
Final: fixed password fallback let a stolen password add admins / replace faces on old-model accounts — password now needs an operator's server-side allowance (flask allow-face-reset, 1 h, used up by re-enroll) and can never add an admin — test_password_needs_operator_permission, test_password_confirmation_cannot_add_admin, test_face_reset_permission_is_used_up_by_reenroll RED→GREEN, suite 151/151
Final: fixed no attempt limit on confirm-it's-you — 5 failures lock 15 min (server-side) — test_step_up_locks_after_five_failures RED→GREEN, suite 151/151
Final: fixed seconds-left rounding (299 vs 300) — ceil
Final: Ruling: added migration 0002 (4 nullable/defaulted admin columns) and applied it to the real DB after a pg_dump backup — required for the server-side fixes — cost if wrong: restore from scratchpad/fipconnect-before-0002.dump
Final: minor (deferred): password confirm form has no double-submit guard; network failure shows raw "Failed to fetch"
Final: minor (deferred): expiry detected in JS by message text rather than an error code
Final: minor (deferred): an unreadable current-model face template (e.g. after a secret-key change) has no in-app recovery
Final: minor (deferred): password /login still has no attempt limit (pre-existing)
