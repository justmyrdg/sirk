# Dashboard charts, KPIs and forecast — short design

Date: 2026-11-22 · Size: medium change (short design)

## Intent
Give the admin dashboard real charts, key numbers (KPIs) and a forecast, built
**only from the existing real data**, and honest about thin data: no invented
lines. (Demo/sample data was discussed and is **on hold** for later.)

## Goals / non-goals
- Goal: KPI cards, three dashboard charts, upgraded Analytics charts, a forecast.
- Goal: every chart and the forecast show a clear "not enough data yet" state.
- Non-goal: demo data, new data fields, status-history tracking, exports.
- Anti-goal: a forecast line drawn from too little history; any chart code or
  data on the client host.

## Approaches
- **A. Chart.js, vendored in `admin_static/` (chosen).** Hover values, responsive,
  little code. Costs one ~200 KB third-party file on the admin site only.
- B. Server-drawn SVG — no library, but more code and less polish.
- C. Python image charts (matplotlib) — heavy install, not interactive; rejected.

## Design
**Numbers (new `fipconnect/services/metrics.py`, pure functions on model rows):**
- KPIs: total inquiries (and this month's), needs attention (Submitted / Under
  Review / Awaiting Client Response), upcoming bookings (Confirmed, date ≥ today),
  conversion rate (existing rule), expected revenue of upcoming confirmed
  bookings, completed (actual) revenue.
- Series (month = `YYYY-MM`, last 12 months, empty months shown as 0):
  inquiries received per month (by submission date); revenue per month —
  expected (Confirmed) vs actual (Completed) by event month.
- Forecast:
  1. **Confirmed pipeline** — expected revenue of Confirmed bookings for the next
     6 months by event month. Real numbers, shown whenever any exist.
  2. **Inquiry projection** — next 3 months = average of the last 3 complete
     months; range = lowest–highest of those 3 months. Shown only when there are
     **at least 6 complete months** since the first inquiry; otherwise the chart
     area says "Forecast available after 6 months of data (N so far)."

"Average days to respond" (mentioned earlier) is left out: the app doesn't record
when an inquiry's status changed, so it can't be computed from existing data.

**Pages:**
- Dashboard: KPI row (6 cards) + charts: inquiries per month, revenue booked vs
  completed, forecast (pipeline bars + projection with range). Recent inquiries
  table stays.
- Analytics: the bar lists become Chart.js charts (inquiries by event month, event
  types, bookings by month); text summaries and the revenue table stay.

**Delivery:** controllers pass the series into the template as JSON in a
`<script type="application/json">` block; `admin_static/charts.js` draws them with
the vendored Chart.js (exact pinned version). No HTML strings in JS. Each chart has a
short text summary and a screen-reader table of its values; with JavaScript off the
summary still shows. Colors follow one consistent palette with readable contrast.

**Tests:** metrics functions (KPIs, month filling, 6-month forecast threshold and
range, pipeline) with fixed dates; pages render the JSON and the "not enough data"
text; client host never gets chart scripts.

## Left to the builder
Exact palette values, chart sizes, card wording, file split inside services.
