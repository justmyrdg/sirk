# SDD ledger — plan: docs/superpowers/plans/2026-11-21-postgres-mvc-backend.md
Setup: no git; backups at C:/Users/Justmyr/AppData/Local/Temp/claude/4a0986ef1abc587e/7593429c-f29d-4f3a-a706-25ed556a1438/scratchpad/backup-before-postgres
Pre-flight: T2 consumes db/models from T1; T3 consumes T1+T2 (face module-attr calls, security, availability); T4 consumes seed_defaults/create_app — consistent
Task 1: Ruling: added a 'flask db upgrade on empty schema matches models' check against seeds too; migration revision id set to '0001' — stable readable id — cost if wrong: none
Task 1: complete (tests: python -m unittest discover -s tests → Ran 48, OK)
Task 2: complete (tests: python -m unittest discover -s tests → Ran 54, OK)
Task 3: Ruling: dropped my test assertion that analytics.actualRevenue is float — with no completed bookings the old app also returned int 0 (sum of empty) — cost if wrong: none, JS treats 0 and 0.0 the same
Task 3: Ruling: added connect_timeout (10s app default, 1s in the DB-down test) — Windows retried a refused connection ~130s — cost if wrong: a very slow DB link over 10s would error instead of hanging
Task 3: Ruling: kept original order (availability check before terms check) in create_inquiry — identical responses — cost if wrong: none
Task 3: Ruling: slow face-service calls happen outside any open transaction (rollback before calling) so no DB lock is held up to 90s — cost if wrong: none
Task 3: complete (tests: python -m unittest discover -s tests → Ran 57, OK)
Task 4: complete (real data imported: 1 admin, 2 inquiries, 3 services; face template decrypts; tests: python -m unittest discover -s tests → Ran 63, OK)
Final review: fresh reviewer (opus) — no critical
Final: fixed test suite could wipe real DB if TEST_DATABASE_URL == DATABASE_URL — test_test_suite_refuses_to_run_against_the_real_database RED→GREEN, suite 69/69
Final: fixed (re-graded Minor→Important) NaN budget from public form broke admin dashboard JSON — test_non_finite_budget_is_rejected RED→GREEN, suite 69/69
Final: fixed (re-graded Minor→Important) double-click delete / concurrent change gave HTML 500 — delete by statement + StaleDataError JSON 409 — test_unexpected_database_conflict_returns_json_not_html RED→GREEN, suite 69/69
Final: fixed concurrent same-email admin registration gave HTML 500 — test_registering_same_email_concurrently_returns_409_json RED→GREEN, suite 69/69
Final: minor (deferred): DB connection stays open while email/SMS send after commit
Final: minor (deferred): complete_booking vs cancel race (admin-only, rare) — no row lock
Final: minor (deferred): import of empty services list keeps the 3 default services
Final: minor (deferred): some import refusal messages name the constraint, not the record id; odd record shapes give a traceback
Final: minor (deferred): two workers may both load face models at first face login (memory peak)
Final: minor (deferred): confirm Render build step can reach internal DATABASE_URL on first deploy
Final: minor (deferred): 5-way reference-code collision → HTML 500 (practically unreachable)
