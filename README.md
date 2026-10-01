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
cp .env.example .env          # the single settings file (local + deploy)
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
flask translate [--dry-run]                                # fill missing LT/EN texts with Claude
flask send-reminders [--dry-run]                           # deadline reminder emails (daily)
flask mailerlite-setup                                     # create MailerLite group + fields (once)
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

## Translations (LT / EN)

Every interface string goes through `app/i18n.py`, and messages the app generates itself are stored as neutral tokens (`app/messages.py`) that display in the viewer's language. Entry content is stored in both languages. The curator writes the detail fields (who it suits, benefit, fee…) in Lithuanian only. Until they are translated, the English view shows them in Lithuanian with an **LT** tag. To fill them in:

```bash
flask translate --dry-run     # how many fields are missing a translation
flask translate               # translate them with Claude (needs ANTHROPIC_API_KEY)
```

After that, the daily refresh translates new entries automatically (`TRANSLATE_BATCH` per run).

## Email reminders (MailerLite)

Logged‑in users who subscribe to an entry get one email **7 days before its deadline** (`REMINDER_DAYS_BEFORE`). All due entries for a user are bundled into one message, and users can switch reminders off on *My subscriptions*. MailerLite has no one‑to‑one sending API, so the app uses MailerLite's automation pattern:

1. Create an API token in MailerLite (Integrations → API) and put it in `.env` as `MAILERLITE_API_KEY`.
2. `flask mailerlite-setup` creates the reminder group and the custom fields (`misc_reminder_subject`, `misc_reminder_list`, `misc_reminder_count`, `misc_reminder_url`, `misc_language`). It prints `MAILERLITE_REMINDER_GROUP_ID` to add to `.env`.
3. In MailerLite, create an **automation**. Trigger: *Joins a group* → that group. Settings: tick **Allow subscribers to re‑enter automation**. Email subject `{$misc_reminder_subject}`, body `{$misc_reminder_list}` plus a button to `{$misc_reminder_url}`. For two languages, use a condition on `misc_language`.
4. `flask send-reminders` (daily 09:00 via the systemd timer) updates each user's fields, then removes and re‑adds them to the group, which fires the automation. `--dry-run` shows what would be sent. Each reminder is recorded, so it is never sent twice; if a deadline moves, a new reminder follows.

Until both `MAILERLITE_API_KEY` and `MAILERLITE_REMINDER_GROUP_ID` are set, reminders are only written to the log. Once they are set, running `flask send-reminders` locally sends real emails to the users in your local database.

## Production deployment — https://misc.lmta.lt/open-calls

No Docker or containers: it is a plain Flask app served by **gunicorn**, managed by **systemd**, behind the existing **nginx**. It runs next to WordPress and the other apps on misc.lmta.lt (museum, ARJournal, journal, booking, kimo, tension…).

- The code lives in `/var/www/open-calls` and runs as the system user `opencalls`.
- Gunicorn listens on a **unix socket**, `/run/opencalls/gunicorn.sock` (owned by `opencalls:www-data`, mode 770), not on a TCP port, so it cannot clash with the other apps' ports.
- `/etc/nginx/snippets/misc-open-calls.conf` is included in the HTTPS `server {}` block right after `server_name`, next to `lmta-museum.conf`. It forwards `/open-calls/` to the socket and sends `X-Forwarded-Prefix`, so every link, redirect and cookie stays under `/open-calls`.
- Its `^~` locations take priority over the regex rules in that block (`\.php$`, the static-file caching rule, `~ /booking(.*)`), and they do not touch any other path.

```bash
./deploy/deploy.sh                 # first deploy and every update
```

There is a single settings file, `.env`, used both locally and on the server. `deploy.sh` runs the tests, uploads the code (excluding local databases and venvs) and your `.env`, then runs `deploy/remote-install.sh` on the server with sudo. Values that must differ in production are set on the server automatically: `DEV_LOGIN=0`, `APP_PREFIX=/open-calls`, `PUBLIC_BASE_URL`, secure HTTPS cookies, and a server‑only `SECRET_KEY` that is generated once and kept across deploys. To change a credential, edit `.env` and deploy again.

SSH goes to `misc.lmta.lt` using your SSH config. If your server login differs from your local username, add `User` under `Host misc.lmta.lt` in `~/.ssh/config`, or set `DEPLOY_SSH=user@misc.lmta.lt` in `.env`.

`remote-install.sh` also:

- creates the `opencalls` system user and copies the code to `/var/www/open-calls`
- installs the merged `.env` with mode 600
- creates the virtualenv, runs migrations and seeds the list the first time
- installs `opencalls.service` (gunicorn) plus the daily **refresh** (04:15) and **reminders** (09:00) timers; on later deploys gunicorn is reloaded gracefully, with no downtime
- writes the nginx snippet and, the first time only, adds its `include` to the `listen 443` block for misc.lmta.lt (the port‑80 redirect block is left alone). A backup goes to `/var/backups/opencalls-nginx/`, and if `nginx -t` fails, both the site file and the snippet are restored
- reloads nginx and checks that `https://misc.lmta.lt/open-calls/` returns 200

Server requirements: a user with SSH and sudo, Python 3.10 or newer with `venv`, `rsync` and `curl`. If the site's nginx file cannot be found automatically, pass `NGINX_SITE=/etc/nginx/sites-available/<file>`. In the Entra app registration, add the redirect URI `https://misc.lmta.lt/open-calls/auth/callback`.

Logs: `journalctl -u opencalls -f`, `journalctl -u opencalls-refresh`, `journalctl -u opencalls-reminders`.

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
deploy/          deploy.sh, remote-install.sh, systemd units/timers, nginx snippet
migrations/      Alembic migrations
```
