# MISC Open Calls

A web app for the Music Innovation Studies Centre (MISC) of the Lithuanian Academy of Music and Theatre (LMTA). It lists open calls, conferences, journal calls, competitions, festivals, academies, residencies and mobility/funding schemes for LMTA students, teachers, artists and researchers.

The database is seeded with the list the MISC coordinator curated on 2026‑09‑28 (`initial_files/MISC-sarasas-2026-09-28.html` → `seed/misc-2026-09-28.json`, 278 entries). The data uses the same schema as the weekly list, so the weekly workflow keeps working (see *Weekly workflow* below).

## Features

| | |
|---|---|
| **Search & filters** | Full‑text search; filter by type, status (open, closing within 14 days, opens soon, closed, not eligible), discipline (38 topics), area (5 topic families), region, country, deadline range, best fit (★), remote participation, free to apply. Filters live in the URL, so any view can be shared as a link. |
| **Live status** | Status labels and "N days left" are worked out from the dates on every request. Nothing goes stale between refresh runs. |
| **Add by link** | An admin pastes a URL. The app fetches the organiser's page, Claude extracts the fields using the MISC curation criteria (scope, geography rules, eligibility traps), and the admin reviews the pre‑filled form before saving. Without an API key, a basic extractor fills in the title, description and deadline. |
| **Manual entry / edit** | Full edit form. Every change is logged in the entry's history. |
| **Suggestions** | Logged‑in users can suggest a link. It is extracted automatically and waits in the admin queue until approved. |
| **Periodic refresh** | `flask refresh` (daily via a systemd timer) moves entries whose deadline passed more than 14 days ago to the archive. It also re‑fetches organiser pages (oldest first), flags broken links and detects page changes. When a page changes, Claude re‑reads it and updates the deadline, event dates and watch→open status. Every automatic change goes to the admin review queue. |
| **Calendar (no account)** | Each entry has an `.ics` download. So does any filtered list. Any filtered list can also be **subscribed** to as a feed (`/feed.ics?...`, webcal) that updates by itself. |
| **Calendar (LMTA account)** | Microsoft login with the institutional account. Users subscribe to entries (☆) and get a personal feed URL (`/feed/u/<token>.ics`) for Outlook, Google or Apple Calendar, with reminders 7 days and 1 day before each deadline. |
| **Map** | Leaflet map of entries by country, with urgent ones in red. Online and international entries are listed separately. |
| **Bilingual** | LT/EN interface; the data already has both languages. |
| **Interop** | `/api/calls?<filters>` (JSON) and `/api/export.json` (the curator's schema 1). `/screen` fills the existing MISC TV‑screen template live from the database. |

## Quick start (local)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # set DEV_LOGIN=1 and ADMIN_EMAILS=you@lmta.lt for local testing
export FLASK_APP=wsgi.py
.venv/bin/flask db upgrade    # create tables
.venv/bin/flask init-db       # seed the curated list (only if the DB is empty)
.venv/bin/flask run --debug   # http://127.0.0.1:5000 — dev login at /auth/dev-login
```

`DEV_LOGIN` only works together with `--debug` or in tests. It is ignored under gunicorn.

Tests: `.venv/bin/pip install pytest && .venv/bin/python -m pytest -q tests`

## CLI

```bash
flask init-db                         # create tables + seed from seed/*.json if empty
flask import MISC-sarasas-2026-10-05.html --drop-expired   # merge a weekly list (HTML or JSON)
flask add-url https://… [--status open]                    # extract one link (pending review by default)
flask refresh [--limit 40] [--no-llm]                      # archive expired + re-check pages
flask make-admin someone@lmta.lt
flask db migrate -m "…" && flask db upgrade                # after model changes
```

## Microsoft (Entra ID) login

1. Entra admin centre → *App registrations* → *New registration* in the LMTA tenant. Choose single tenant.
2. Redirect URI (Web): `https://<your-host>/auth/callback`
3. *Certificates & secrets* → new client secret.
4. Put the values in `.env`: `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_TENANT_ID` (the directory ID). Set `ALLOWED_EMAIL_DOMAINS=lmta.lt` (add the student domain if it is different) and `ADMIN_EMAILS=`.

Logins from other tenants are rejected. Only the delegated `User.Read` permission is used.

## Claude API

Set `ANTHROPIC_API_KEY` to turn on AI extraction and AI re‑checks. The model defaults to `claude-opus-5-5` with `CLAUDE_EFFORT=medium`. Requests use structured output (a Pydantic schema), so the fields always parse. They also enable the API's server‑side refusal fallback (`fallbacks: "default"`). Cost is controlled by `REFRESH_BATCH` (pages per run) and `REFRESH_MIN_AGE_DAYS`. Claude is only called when a page's text has actually changed.

## Production deployment (Linux VM)

```bash
sudo useradd -r -m -d /srv/opencalls opencalls
# copy the project to /srv/opencalls, then:
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # SECRET_KEY, DATABASE_URL (PostgreSQL), MS_*, ANTHROPIC_API_KEY,
                       # SESSION_COOKIE_SECURE=1, PREFERRED_URL_SCHEME=https, DEV_LOGIN=0
FLASK_APP=wsgi.py .venv/bin/flask db upgrade && FLASK_APP=wsgi.py .venv/bin/flask init-db
sudo cp deploy/opencalls*.service deploy/opencalls-refresh.timer /etc/systemd/system/
sudo systemctl enable --now opencalls opencalls-refresh.timer
sudo cp deploy/nginx.conf /etc/nginx/sites-available/opencalls   # then certbot --nginx
```

SQLite is fine for a single server with little traffic. PostgreSQL is recommended for production (`psycopg` is in the requirements). Back up the database daily.

## Weekly workflow (compatibility)

The coordinator's weekly Claude routine produces `MISC-sarasas-<date>.html` with an embedded `misc-duomenys` JSON block. Upload that file in **Admin → Import weekly list** (or run `flask import`). Entries are merged by URL + title, changed fields are logged, and expired entries are skipped. The routine can also *read* the current state from `/api/export.json` instead of last week's artifact.

## Project layout

```
app/
  models.py      Call, CallChange (audit), User, Subscription, RefreshRun
  taxonomy.py    types, topics/families, countries → regions + coordinates
  search.py      filters shared by the list, API, calendar exports and map
  extract.py     page fetch + Claude structured extraction + heuristic fallback
  refresh.py     archive + re-check job
  importer.py    weekly JSON/HTML import (upsert)
  ics.py         iCalendar generation
  auth.py        Microsoft Entra ID login (MSAL)
  views.py, admin.py, cli.py, scheduler.py
  screen_template.html   the MISC TV-screen template, filled by /screen
seed/            initial curated data
deploy/          systemd, timer, nginx
migrations/      Alembic migrations
```
