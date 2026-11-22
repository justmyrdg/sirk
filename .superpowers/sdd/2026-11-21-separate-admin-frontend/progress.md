# SDD ledger — plan: docs/superpowers/plans/2026-11-21-separate-admin-frontend.md
Setup: Ruling: no git repo — no worktree/commits; originals backed up to C:/Users/Justmyr/AppData/Local/Temp/claude/4a0986ef1abc587e/7593429c-f29d-4f3a-a706-25ed556a1438/scratchpad/backup-original — cost if wrong: none, backup allows restore
Pre-flight: Task2 consumes is_admin_host/admin_host_only//api/admin/bootstrap/CLIENT_URL from Task1 — consistent
Task 1: Ruling: pytest not installed — used `python -m unittest discover -s tests` — cost if wrong: none, same tests
Task 1: complete (tests: python -m unittest discover -s tests → Ran 27, OK)
Task 2: Ruling: client header highlights "Check status" in the slot the Admin button used — keeps nav layout — cost if wrong: cosmetic
Task 2: Ruling: added a Loading… state on the admin page before bootstrap returns — avoids flashing the setup form to an existing install — cost if wrong: none
Task 2: Ruling: manual browser click-through replaced by live curl smoke test on port 5055 (user's own server held 5000, left untouched) — JS rendering not exercised in a real browser — cost if wrong: a UI bug the user finds on first load
Task 2: complete (tests: python -m unittest discover -s tests → Ran 31, OK)
Final: fixed Host-header spoof of default admin.localhost on deployed servers — test_default_admin_host_only_answers_local_requests RED→GREEN, suite 33/33
Final: fixed README false 'fails closed' claim + added reverse-proxy Host guidance (docs only, no test)
Final: minor (deferred): FIP_CLIENT_URL default points View site at localhost if unset in production (README now says always set it)
Final: minor (deferred): admin page stays on Loading… if admin bootstrap fails
Final: minor (deferred): Add admin failure loses typed details
Final: minor (deferred): camera stream not stopped when switching tabs mid-capture (pre-existing)
Final: minor (deferred): cookie-isolation test proves host check, not cookie rejection
Final: minor (deferred): FIP_CLIENT_URL scheme not validated (operator-controlled)
Final: Ruling: reviewer's declined items (fresh-install setup race, no Secure cookie flag, public inquiry rate limits) left as-is — predate this change and spec kept them unchanged — cost if wrong: existing risks remain
Final review: fresh reviewer (opus)
