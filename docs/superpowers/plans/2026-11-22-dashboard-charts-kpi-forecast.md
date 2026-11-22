# Dashboard Charts, KPIs and Forecast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add KPI cards, Chart.js charts and an honest forecast to the admin dashboard and analytics page, built only from existing data.

**Architecture:** A pure-function `fipconnect/services/metrics.py` turns model rows into KPIs, monthly series and a forecast. Controllers pass the series into templates as JSON in `<script type="application/json">`. `admin_static/charts.js` draws them with a vendored, version-pinned Chart.js.

**Tech Stack:** Flask/Jinja, Chart.js 4.4.1 (vendored UMD build), unittest.

**Spec:** `docs/superpowers/specs/2026-11-22-dashboard-charts-kpi-forecast-design.md`

**Note:** No git, so no commit steps. Back up `fipconnect/`, `templates/`, `admin_static/`, `static/css/` and `tests/` first. Test command: `python -m unittest discover -s tests`. Load the `dataviz` skill before writing any chart code or choosing colors.

## Global Constraints
- **Data:** only existing data, with no invented values. The projection appears only with ≥ 6 complete months since the first inquiry; otherwise the text reads exactly "Forecast available after 6 months of data (N so far)."
- **Chart files:**
  - Chart.js and `charts.js` live in `admin_static/` and never load on the client host.
  - Chart.js is pinned to exact version 4.4.1 at `admin_static/vendor/chart.umd.min.js`.
- **JavaScript rules:** no HTML strings in JS, and the data comes from JSON blocks via `JSON.parse(el.textContent)`.
- **Months:** keys are `YYYY-MM`. A series covers the last 12 months ending with the current month, and empty months are 0.
- **Accessibility:** every chart has a visible text summary and a visually hidden `<table>` of its values.

## Review Focus
1. Zero data (fresh database): every page renders, the KPIs show 0 or ₱0, and charts show an empty state, not a JS error. Tests: Task 2 `test_dashboard_with_no_data_renders_empty_states` and Task 3 `test_analytics_with_no_data`.
2. Year boundaries: a series that crosses December→January orders and labels months correctly. Test: Task 1 `test_month_series_crosses_year`.
3. The current partial month must not count as "complete" for the forecast threshold. Test: Task 1 `test_projection_threshold_excludes_current_month`.
4. Cancelled or Completed bookings must not count as upcoming or pipeline. Test: Task 1 `test_kpis_count_only_confirmed_upcoming`.
5. A JSON block containing `</script>`-like text (e.g. an event name) must not break the page. Test: Task 2 `test_chart_json_is_escaped`.

---

### Task 1: Metrics service

**Files:** Create `fipconnect/services/metrics.py` and `tests/test_metrics.py`.

**Interfaces (produces):**
- `month_keys(today: date, count: int = 12) -> list[str]`: the last `count` months, oldest first, ending with today's month.
- `kpis(inquiries, bookings, today) -> dict`. Keys:
  - `total`, `this_month`, `pending`, `upcoming`, `conversion`: integers.
  - `expected_upcoming` (Decimal): the sum of `expected_revenue` over Confirmed bookings with date ≥ today.
  - `actual_completed` (Decimal): the sum of `actual_revenue` over Completed bookings.
- `inquiries_per_month(inquiries, today) -> {"labels": [...12 YYYY-MM], "counts": [...]}`. Counts are by `created_at` month.
- `revenue_per_month(bookings, today) -> {"labels", "expected": [floats], "actual": [floats]}`:
  - `expected` is Confirmed + Completed bookings' `expected_revenue`, by event month;
  - `actual` is Completed bookings' `actual_revenue`, by event month.
- `forecast(inquiries, bookings, today) -> dict`:
  - `pipeline`: `{"labels": next 6 months starting with the current month, "expected": [floats]}`, from Confirmed bookings with date ≥ today.
  - `months_of_history`: the number of complete months from the first inquiry's month up to, but not including, the current month (0 when there are no inquiries).
  - `projection`: `None` when `months_of_history < 6`. Otherwise `{"labels": next 3 months after the current month, "estimate": avg of last 3 complete months (rounded to 1 decimal), "low": min, "high": max}`.

  Inquiries and bookings are model rows; `today` is a `date`.

- [ ] **Step 1: Write failing tests** (pure functions, using simple stand-in objects with the model attribute names; no database)
- `test_month_series_crosses_year`: with today = 2027-01-15, `month_keys(today, 3)` == `["2026-11", "2026-12", "2027-01"]`.
- `test_inquiries_per_month_fills_empty_months`: two inquiries created in 2026-11 and one in 2027-01. The labels are 12 entries ending with "2027-01"; the 2026-11 count is 2, 2026-12 is 0, and 2027-01 is 1.
- `test_kpis_count_only_confirmed_upcoming`:
  - bookings: Confirmed in the future (₱10,000 expected), Confirmed in the past, Cancelled in the future, Completed (₱5,000 actual);
  - inquiries: Submitted and Approved;
  - expected: `upcoming == 1`, `expected_upcoming == Decimal("10000")`, `actual_completed == Decimal("5000")`, `pending == 1`.
- `test_revenue_per_month_splits_expected_and_actual`: values are floats in the right months.
- `test_projection_threshold_excludes_current_month`:
  - first inquiry 2026-07-03, today = 2027-01-10: 2026-07…2026-12 is 6 complete months, so `months_of_history == 6` and the projection is not None;
  - today = 2026-12-31: 5 months, so the projection is None.
- `test_projection_average_and_range`: monthly counts for the last 3 complete months of 2, 4 and 6 give `estimate == 4.0`, `low == 2` and `high == 6`, with labels for the next 3 months.
- `test_pipeline_next_six_months`: a Confirmed booking 2 months ahead appears at index 2 of `pipeline.expected`, and a booking 8 months ahead isn't included.
- `test_empty_data`: every function works with empty lists. The KPIs are 0, the series are all zeros, and the projection is None with `months_of_history == 0`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_metrics`
Expected: ImportError.

- [ ] **Step 3: Implement `metrics.py`**

- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover -s tests`
Expected: PASS.

### Task 2: Dashboard KPIs and charts

**Files:**
- Create: `admin_static/vendor/chart.umd.min.js` (download Chart.js 4.4.1 UMD from `https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js` into a fresh scratch dir, check that it starts with the Chart.js license header, then copy it in), `admin_static/charts.js`, `templates/partials/chart.html`
- Modify: `templates/admin/dashboard.html`, `fipconnect/controllers/workspace_pages.py` (`dashboard`), `static/css/styles.css`
- Create: `tests/test_dashboard_charts.py`

**Interfaces:**
- Consumes: Task 1 functions.
- Produces:
  - The macro `chart(id, title, summary, kind, data, table_headers, table_rows, empty_message=None)` in `partials/chart.html`. It renders:
    - a `<figure class="chart-card">` with a title, a `<canvas data-chart="{{ id }}" role="img" aria-label="{{ summary }}">`, and a visible summary;
    - a `<table class="visually-hidden">`;
    - `<script type="application/json" id="chart-data-{{ id }}">{{ {"kind": kind, **data} | tojson }}</script>`.

    When `empty_message` is set, the macro renders a `<p class="chart-empty">` instead of the canvas.
  - `charts.js` finds `[data-chart]`, parses the matching JSON, and creates a Chart with `kind` ∈ `line` | `bar` | `forecast`. `forecast` is the pipeline as bars plus, when present, the projection as a point with low–high error lines drawn by a small plugin. Colors come from CSS custom properties read with `getComputedStyle`.
  - The dashboard loads `vendor/chart.umd.min.js` and then `charts.js` (admin `base.html` gets a `{% block extra_scripts %}`).

- [ ] **Step 1: Write failing tests** (`DatabaseTestCase`, signed in through the setup endpoint as in `tests/test_admin_pages.py`)
- `test_dashboard_shows_six_kpis`: the page contains "Total inquiries", "Needs attention", "Upcoming bookings", "Conversion", "Expected revenue" and "Completed revenue".
- `test_dashboard_embeds_chart_data`: there are blocks `chart-data-inquiries`, `chart-data-revenue` and `chart-data-forecast`. Their JSON parses, and `inquiries.labels` has length 12.
- `test_dashboard_with_no_data_renders_empty_states`: a fresh database returns 200 and contains "Forecast available after 6 months of data (0 so far)."
- `test_chart_json_is_escaped`: an inquiry with event name `</script><b>x` still gives a page whose JSON block parses, and the raw `</script><b>` isn't inside the JSON block.
- `test_chart_scripts_not_on_client_host`: client `/` doesn't contain `chart` script tags, and `/admin-static/vendor/chart.umd.min.js` on the client host returns 404.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_dashboard_charts`
Expected: FAIL.

- [ ] **Step 3: Load the `dataviz` skill, then implement**

- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover -s tests`
Expected: PASS.

### Task 3: Analytics charts, docs, check

**Files:** Modify `templates/admin/analytics.html`, `fipconnect/controllers/workspace_pages.py` (`analytics_page`), `README.md`. Create `tests/test_analytics_charts.py`.

**Interfaces:** Consumes the Task 2 macro and `charts.js`; there are new chart kinds `bar` (event months, event types, bookings by month) and `hbar` (event types).

- [ ] **Step 1: Write failing tests**
- `test_analytics_embeds_charts`: it has blocks `chart-data-event-months`, `chart-data-event-types` and `chart-data-booking-months`, and the revenue table is still present.
- `test_analytics_with_no_data`: it returns 200 and shows each chart's empty message.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_analytics_charts`
Expected: FAIL.

- [ ] **Step 3: Implement.** Replace the bar-list macro with `chart(...)` calls, and keep the peak-month and revenue panels.

- [ ] **Step 4: Run the full suite and check in the running app**

Run `python -m unittest discover -s tests` (expected: PASS). Then start the app on port 5055 and confirm that `/admin-static/vendor/chart.umd.min.js` and `/admin-static/charts.js` return 200 on the admin host, and run `node --check admin_static/charts.js`.

- [ ] **Step 5: README.** Add a sentence about the dashboard KPIs, the charts, and the forecast threshold.
