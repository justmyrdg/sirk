# Minimum booking lead time (7 days) — short design

Date: 2026-11-22 · Size: small change · Approved in conversation

## Intent
Clients must request event dates at least 7 days ahead (team prep time). Today
through today+6 are closed; today+7 is the first open date (e.g. today Nov 22 →
earliest Nov 29). Clients must be clearly told this up front.

## Design
- Setting `FIP_MIN_LEAD_DAYS` (default 7) → `app.config["MIN_LEAD_DAYS"]`.
- "Today" is the Philippine date (`metrics.local_today()`).
- `earliest_bookable(today, lead_days) = today + lead_days`.
- **Server rule** (client inquiries only): `submit_inquiry` refuses an event date
  before the earliest date with 400 "Please choose a date at least 7 days from
  today." (number from the setting). Same check order position as the past-date rule.
- **Not restricted:** admin approvals and admin date blocks.
- **Calendar (client):** days before the earliest date (and after today) show
  "Too soon", greyed (`is-too-soon`), not clickable; legend gains "Too soon (less
  than 7 days away)".
- **Highlighting for clients:** a notice on Availability and Inquire: "Book at
  least 7 days ahead. The earliest date you can request is <Sat, Nov 29, 2026>.";
  the inquiry date input's `min` is the earliest date and its hint repeats it; a
  `?date=` link to a too-soon day still prefills but the notice explains.
- Tests: rule boundary (today+6 refused, today+7 accepted), setting respected,
  admin approval unaffected, calendar labels, notices, input min.
