# SDD ledger — plan: docs/superpowers/plans/2026-11-22-dashboard-charts-kpi-forecast.md
Setup: no git; backups at C:/Users/Justmyr/AppData/Local/Temp/claude/4a0986ef1abc587e/7593429c-f29d-4f3a-a706-25ed556a1438/scratchpad/backup-before-charts; execution: native (user's standing choice)
Pre-flight: T2/T3 consume T1 metrics + T2 chart macro/charts.js — consistent
Task 1: complete (tests: python -m unittest discover -s tests → OK; test_metrics 8/8)
Task 2: Ruling: forecast split into two charts (₱ pipeline bars | inquiry-count projection) instead of one combined chart — one chart can't carry pesos and counts without a dual axis (dataviz non-negotiable) — cost if wrong: none
Task 2: Ruling: palette = #2a78d6 (blue) + brand orange #f15a24; brand navy #173f7a failed the lightness band for marks (validator) — kept navy for UI, not data — cost if wrong: cosmetic
Task 2: Ruling: chart data shape is {kind, format, labels, series:[{name, values}], range?} (plan said separate keys per chart) — one shape for every chart — cost if wrong: none
Task 2: Ruling: test fixed to book the event today — "Revenue by event month" covers the last 12 months, so a next-month booking correctly appears only in the pipeline — cost if wrong: none
Task 2: complete (tests: python -m unittest discover -s tests → Ran 124, OK)
Task 3: complete (tests: python -m unittest discover -s tests → Ran 127, OK; live: chart files 200 on admin host, 404 on client host)
Final review: fresh reviewer (opus) — no critical
Final: fixed month buckets/"today" used server UTC (7am PH on the 1st counted as previous month) — now Philippine time (UTC+8) — test_months_follow_philippine_time, test_local_today_uses_philippine_date RED→GREEN, suite 131/131
Final: fixed projection chart showed the partial current month as a real point before the forecast — history now ends at last complete month — test_projection_history_ends_at_last_complete_month RED→GREEN, suite 131/131
Final: fixed screen-reader table read "None" for missing values — now "—" and counts without ".0" — test_hidden_table_shows_dash_for_missing_values RED→GREEN, suite 131/131
Final: Ruling: "Booked (expected)" revenue counts Confirmed AND Completed bookings (spec said Confirmed) — so booked vs completed compare the same events — cost if wrong: booked bar slightly higher than "confirmed only"
Final: minor (deferred): Analytics booking/event-month charts skip empty months, and the peak month can be outside the drawn window
Final: minor (deferred): analytics summary macro splits on "|" (breaks if an event name contains "|")
Final: minor (deferred): chart summary is read twice by screen readers (aria-label + visible text)
Final: minor (deferred): vendored Chart.js references a source map that isn't shipped (DevTools logs a 404)
Final: minor (deferred): .visually-hidden lacks margin/padding/border reset; chart surface/tooltip colors not tokenised
Final: minor (deferred): the "Inquiries per month" chart's current month is partial without a "(so far)" label
Final: minor (deferred, pre-existing): past-date checks elsewhere still use the server's date, not Philippine date
