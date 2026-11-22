# FIPConnect

FIPConnect is a Flask web application for event inquiries, booking management, availability, and descriptive analytics. Clients do not create accounts; only the FIP administrator signs in.

## Project structure

```text
FIPConnect/
├── app.py                 # entry point (python app.py / gunicorn app:app)
├── fipconnect/            # the application (MVC)
│   ├── __init__.py        # create_app(): config, database, blueprints
│   ├── config.py          # settings from the environment / .env
│   ├── models/            # database tables (SQLAlchemy) and their JSON shapes
│   ├── controllers/       # routes: client pages, admin pages, face-camera API
│   ├── services/          # security, face recognition, notifications,
│   │                      # availability, analytics
│   └── cli.py             # flask import-json
├── migrations/            # database schema history (Alembic)
├── requirements.txt
├── package.json
├── face_service.cjs
├── README.md
├── templates/             # the views (Jinja), rendered by the controllers
│   ├── base.html, error.html
│   ├── client/            # home, availability, inquire, thanks, status
│   ├── admin/             # login, setup, dashboard, inquiries, schedule,
│   │                      # services, analytics, landing, add admin, face
│   └── partials/          # calendar, tables, status labels, face camera
├── static/
│   ├── css/
│   │   └── styles.css
│   ├── images/
│   │   └── logo_flare.png
│   └── js/
│       └── site.js        # client: gallery arrows, old-link redirects
├── admin_static/
│   ├── admin.js           # admin: face camera + delete confirmations
│   ├── charts.js          # admin: draws dashboard/analytics charts
│   └── vendor/chart.umd.min.js  # Chart.js 4.4.1
├── tests/                 # run against a separate test database
└── instance/              # session/encryption key (not committed)
```

## Run locally

1. Create and activate a Python virtual environment.
2. Install dependencies with `python -m pip install -r requirements.txt`.
3. Install the JavaScript face-recognition dependencies with `npm install`.
4. Create two PostgreSQL databases, `fipconnect` and `fipconnect_test`, and set `DATABASE_URL` and `TEST_DATABASE_URL` in `.env` (see `.env.example`).
5. Create the tables with `flask --app app db upgrade`.
6. Optional: copy records from an old JSON data file with `flask --app app import-json` (reads `instance/fipconnect.json`; refuses if the database already has data).
7. Start the app with `python app.py`.
8. Clients must request event dates at least 7 days ahead (change with `FIP_MIN_LEAD_DAYS`); the Availability and Inquire pages say so and show the earliest date, the calendar marks closer days "Too soon", and the server refuses them. Admins are not limited when approving or blocking dates.
9. Open the client site at <http://localhost:5000> (pages: `/availability`, `/inquire`, `/status`). Loopback IP URLs such as `http://127.0.0.1:5000` automatically redirect to `localhost`.
9. Set `FIP_ALLOW_SETUP=true` in `.env` (or the terminal) and open the admin site at <http://admin.localhost:5000> (sign in at `/login`; workspace pages `/inquiries`, `/schedule`, `/services`, `/analytics`, `/landing`). The first visit shows first-time setup for the administrator account. Afterwards set `FIP_ALLOW_SETUP=false` and restart. While it is off (the default), first-time setup is refused, so nobody can claim the first admin account on a new server. Browsers treat `*.localhost` as this computer and as a secure origin, so camera access works there.

The client site has no admin link, login, or admin code. Admin pages, the admin script, and every admin/login API respond only on the admin host; on any other host they return 404.

Records are stored in PostgreSQL. The session/encryption key is in `instance/secret.key` (or `FIPCONNECT_SECRET_KEY`); keep it, because enrolled faces can only be read with the same key.

Run the tests with `python -m unittest discover -s tests`. They use `TEST_DATABASE_URL` only and wipe that database, so never point it at real data.

### Changing the database schema

Edit the models in `fipconnect/models/`, then run `flask --app app db migrate -m "describe the change"`, review the new file in `migrations/versions/`, and apply it with `flask --app app db upgrade`. (The "Install python-dotenv" tip Flask prints is harmless: the app reads `.env` itself.)

The first administrator creates an account using an email and password, then enrolls their face using the browser camera. Additional administrators are added by a signed-in administrator with **Add admin** in the admin header (`/admins/new`). Before adding an admin or re-enrolling a face, the signed-in admin must first confirm it's them with a live face scan matched against their own saved face ; the confirmation lasts 5 minutes, is used up by the action (enforced in the database, so an old copy of the session cookie can't reuse it), and 5 wrong attempts lock it for 15 minutes. An admin whose saved face is from the old model can't be face-checked: someone with server access runs `flask --app app allow-face-reset EMAIL` (valid one hour), and that admin can then confirm with their password to re-enroll their face only — adding admins always needs a face confirmation. So a stolen password alone can't add an admin or replace a face. Face matching has no liveness check, so a clear photo of the real admin could still pass this step; there is no public signup. Each account can sign in with its own email and password or its enrolled face. Face detection and matching run in a local server-side JavaScript service using `@vladmandic/face-api` and its 128-value face descriptor model. Flask starts the service on `127.0.0.1:5018` the first time face recognition is used; the service accepts requests only from Flask using a token derived from the stable Flask secret key. The first recognition may take longer while the JavaScript service loads its models. The camera photo is processed in memory and discarded; only the face descriptor is stored, encrypted using a key derived from Flask's stable secret key. Keep `instance/secret.key` (or `FIPCONNECT_SECRET_KEY`) private and stable, because rotating it makes saved face templates unreadable. Face matching is not liveness detection and cannot reliably stop photo/video spoofing; keep a strong password fallback. Use HTTPS when deploying so browsers allow camera access.

Existing face templates created with DeepFace use a different model and cannot be compared to the JavaScript descriptors. Those admins can still sign in with their password, then select **Re-enroll face** in the admin header to replace their saved template. Re-enrollment does not change the account password or other records. The `import-json` command also accepts old single-admin JSON files.

For deployment, set a private `FIPCONNECT_SECRET_KEY`, keep debug mode off, and use a production WSGI server such as gunicorn (see "Deploying on Render").

The admin dashboard shows KPI cards (inquiries, items needing attention, upcoming bookings, conversion, expected and completed revenue), monthly charts, and a forecast built only from recorded data: expected revenue from confirmed bookings for the next 6 months, and an inquiry projection (average of the last 3 complete months, with their low–high range) that appears once there are 6 complete months of data. Charts use Chart.js 4.4.1, stored in `admin_static/vendor/` and served only on the admin host; each chart also has a text summary and a screen-reader table.

Pages are rendered on the server from the Jinja templates in `templates/`, and every form works without JavaScript except the face camera. Forms carry a CSRF token; success and error messages appear at the top of the page.

## Settings file (.env)

`python app.py` reads settings from a `.env` file in the project folder (see `.env.example` for every option). Variables already set in the terminal take priority. `.env` is listed in `.gitignore`; keep it private. When running under a production WSGI server, set these as real environment variables in your hosting dashboard instead.

## Deploying the admin on a subdomain

Point both DNS names (for example `yoursite.com` and `admin.yoursite.com`) at the same app, and set:

- `FIP_ADMIN_HOST` — the admin hostname, for example `admin.yoursite.com` (default `admin.localhost`). Case and port are ignored.
- `FIP_CLIENT_URL` — the public site URL used by the admin's "View site" links, for example `https://yoursite.com` (default `http://localhost:5000`).

Always set `FIP_ADMIN_HOST` and `FIP_CLIENT_URL` when deploying. Without `FIP_ADMIN_HOST`, the built-in `admin.localhost` is accepted only from requests made on the server machine itself.

If the app runs behind a reverse proxy (nginx, Caddy, a hosting platform), the proxy must pass the original `Host` header through — for nginx, `proxy_set_header Host $host;`. Otherwise Flask sees the proxy's upstream name, and the admin subdomain will show the client site.

Separating the hosts hides the admin from clients; it is not a replacement for authentication. The admin password and face login still protect the admin, so keep the admin password strong. For extra protection, restrict the admin subdomain at the proxy (for example by IP allow-list). Login sessions are per host: signing in on the admin site does not create a session on the client site.

## Client email and SMS notifications

FIPConnect can send a confirmation when an inquiry is submitted and a new notification whenever an administrator changes its status (including Approved, Declined, and Cancelled). Both messages include the client's unique `FIP-XXXXXXXX` tracking/reference code. The existing **Check inquiry status** page already accepts that code, so clients do not need to create an account.

Notifications are optional until provider credentials are configured. The inquiry and status update are saved even if an email or SMS provider is unavailable; notification failures are written to the Flask server log.

### Email (SMTP)

Set these environment variables before starting Flask:

- `FIP_SMTP_HOST` — SMTP server hostname
- `FIP_SMTP_PORT` — usually `587` for STARTTLS or `465` for implicit SSL
- `FIP_SMTP_USERNAME` — SMTP username (often the full email address)
- `FIP_SMTP_PASSWORD` — SMTP password or provider app password
- `FIP_SMTP_FROM` — sender email address (can be the same as the username)
- `FIP_SMTP_USE_SSL` — set to `true` only when using implicit SSL on port 465; otherwise omit or set `false`

For Gmail, use an app password where Google account security settings allow it; do not put your normal account password in the project files.

### SMS (Twilio)

Create/configure a Twilio account and a sender number that is enabled to send SMS to your clients' destinations. Set:

- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_FROM_NUMBER` — your Twilio SMS-enabled sender number in international format

Client mobile numbers should preferably be saved in international E.164 format (for example, `+639XXXXXXXXX`). The app also converts common Philippine `09XXXXXXXXX` and `9XXXXXXXXX` formats to `+63` before sending. Twilio account verification, destination permissions, sender registration, and applicable message charges may apply.

### Example: Windows PowerShell

Set values in the terminal before launching the app (replace the example values with your provider's actual credentials):

```powershell
$env:FIP_SMTP_HOST = "smtp.gmail.com"
$env:FIP_SMTP_PORT = "587"
$env:FIP_SMTP_USERNAME = "your-sending-address@example.com"
$env:FIP_SMTP_PASSWORD = "your-email-app-password"
$env:FIP_SMTP_FROM = "your-sending-address@example.com"
$env:TWILIO_ACCOUNT_SID = "your-twilio-account-sid"
$env:TWILIO_AUTH_TOKEN = "your-twilio-auth-token"
$env:TWILIO_FROM_NUMBER = "+1XXXXXXXXXX"
python app.py
```

Do not commit credentials to GitHub or share them in screenshots. For production hosting, configure these as private environment variables in the hosting provider's dashboard and use HTTPS.

### Notification behavior

- On submission: sends a received/confirmation message with the tracking code.
- On status change: sends the updated status and same tracking code.
- Re-saving the same status does not send a duplicate notification.
- If one provider fails, the other provider is still attempted.

## Deploying on Render

1. Create a **PostgreSQL** database on Render.
2. Create a **Web Service** from the repository:
   - Build Command: `pip install -r requirements.txt && npm install && flask --app app db upgrade`
   - Start Command: `gunicorn --workers 2 --threads 4 --bind 0.0.0.0:$PORT app:app`
3. Environment variables: `DATABASE_URL` (the database's **internal** URL; `postgres://` URLs are accepted), `PYTHON_VERSION=3.12.0`, `FIPCONNECT_SECRET_KEY` (generate once, never change), `FIP_ADMIN_HOST`, `FIP_CLIENT_URL`, `FIP_ALLOW_SETUP` (true only while creating the first admin), and optional SMTP/Twilio values.
4. Add both custom domains (e.g. `yoursite.com` and `admin.yoursite.com`) to the same service. No persistent disk is needed: data lives in PostgreSQL.

**Moving your local data to Render:** set Render's `FIPCONNECT_SECRET_KEY` to the exact contents of your local `instance/secret.key` (otherwise imported face templates can't be decrypted), then from your computer run `flask --app app import-json` with `DATABASE_URL` set to the Render database's **external** URL in that terminal.
