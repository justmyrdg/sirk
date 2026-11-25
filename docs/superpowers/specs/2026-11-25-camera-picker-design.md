# Choose which camera the face scan uses — short design

Date: 2026-11-25 · Size: small change (short design, approved in chat)

## Intent
Admins with more than one camera (webcam + USB camera, phone front/back) can pick
which one the face scan uses, instead of whatever the browser defaults to.

## Design
- A "Camera" dropdown in the face camera panel (`templates/partials/face_camera.html`),
  shown only when the device has 2+ cameras; options are the camera names
  (fallback "Camera 1", "Camera 2" when the browser hides names).
- Changing it switches the live video immediately, without closing the panel.
- The choice is remembered per browser (localStorage, wrapped in try/catch); if the
  remembered camera is gone, fall back to the default front camera.
- Applies to every face flow (sign-in, setup, add admin, enroll/re-enroll, confirm it's you)
  since they share the partial and `admin_static/admin.js`.
- Known limit: browsers reveal camera names only after camera permission, so the list
  appears once the video has started.

## Approaches
- **Dropdown in the camera panel (chosen)** — one place, works for all flows.
- Settings page for a default camera — more UI, and the choice is per device anyway.

## Tests
Template has the labelled select (hidden by default); admin.js enumerates video inputs,
starts the stream with the chosen deviceId, stores the choice inside try/catch, and still
builds no HTML (no innerHTML).
