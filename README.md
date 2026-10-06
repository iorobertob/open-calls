# MISC Open Calls

A web app for the Music Innovation Studies Centre (MISC) of the Lithuanian Academy of Music and Theatre (LMTA). It lists open calls, conferences, journal calls, competitions, festivals, academies, residencies and mobility/funding schemes for LMTA students, teachers, artists and researchers.

The database is seeded with the list the MISC coordinator curated on 2026‑09‑28 (`initial_files/MISC-sarasas-2026-09-28.html` → `seed/misc-2026-09-28.json`, 278 entries). The data uses the same schema as the weekly list, so the weekly workflow keeps working (see *Weekly workflow* below).

## Features

| | |
|---|---|
| **Browse & filter** | The home page starts with four **fields**: Music and Sound, Theatre, Cinema, Dance and Performance. Choosing a field shows its **categories**, and choosing a category shows its **sub-disciplines** (several can be selected: any of them). Each choice shows how many results it gives. Also: full‑text search, type, status, region, country, deadline range, best fit (★), remote, free. Everything is in the URL, so views can be shared. Admins edit the field → category → sub‑discipline tree in **Admin → Fields & disciplines**. |
| **Live status** | Status labels and "N days left" are worked out from the dates on every request. Nothing goes stale between refresh runs. |
| **Add by link** | An admin pastes a URL. The app fetches the organiser's page, Claude extracts the fields using the MISC curation criteria (scope, geography rules, eligibility traps), and the admin reviews the pre‑filled form before saving. Without an API key, a basic extractor fills in the title, description and deadline. |
| **Manual entry / edit** | Full edit form. Every change is logged in the entry's history. |
| **Suggestions** | Logged‑in users can suggest a link. It is extracted automatically and waits in the admin queue until approved. |
| **Weekly refresh** | `flask refresh`, every Monday night via a systemd timer. It archives entries whose deadline passed more than 14 days ago and fills in missing translations. It also re‑reads the pages of current calls: a page counts as changed when its main text (without menus, footers and cookie banners) differs from last week's, and only then is Claude called. If a page now shows a *different* call (a new edition or theme), a new entry is created for review instead of overwriting the existing one. |
| **Series** | Recurring sources (journals, conferences, festivals, programmes). Their pages are scanned weekly and new calls become pending entries for approval. An "expected next call" placeholder (e.g. *Expected around September 2027*) appears under *Opens soon* and is replaced by the real call once it is approved. Users can **follow** a series. |
| **E‑mail (SMTP)** | One e‑mail per person per day at most: deadline reminders (from 1 month before, then weekly), new calls in followed series, and changes to subscribed calls. Admins get a daily digest of entries to review. Every e‑mail has a one‑click unsubscribe link. |
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
flask send-notifications [--dry-run]                       # daily e-mails (reminders, series news, admin digest)
flask mail-test you@lmta.lt                                # check the SMTP settings (or Admin → E-mails → Send a test)
flask classify-fields [--dry-run]                          # Claude adds Theatre / Cinema / Dance fields where they belong
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

## Series and the life of an entry

Each entry is **one specific call**: one edition or theme, with its own deadline. A **series** groups the calls of a recurring source and keeps watching it between calls:

```
call 2026 (open) ─deadline─▶ closed ─14 days─▶ archived
                                │
                                └─▶ placeholder "next call — expected around Sept 2027" (Opens soon)
weekly scan of the series page finds the 2027 call ─▶ new pending entry ─approve─▶ open
                                                       (placeholder removed, followers e-mailed)
```

- **Create series:** **Admin → Series → Suggested series** groups the existing entries by website. Untick what doesn't belong, check the name and the page address (where new calls are published), and create. A single entry can also become a series ("Create a series from this entry" on its edit page).
- **Expected next call:** worked out from when previous calls appeared, plus the rhythm (yearly or twice a year). You can also set a fixed usual month. If the expected call hasn't been found within about 3 months of that date, the placeholder is archived and the admins are told to check.
- **Series have to be created once.** The upgrade adds the series feature but doesn't create any series, because grouping needs a human eye (e.g. *societymusictheory.org* is a listing of many organisers, not one series). On each installation (development and production separately, since each has its own database), go to **Admin → Series → Suggested series** and create the series you want. From then on the weekly job maintains them.
- **New entries are never published automatically.** Calls found on series pages, user suggestions and different editions found during re‑checks all wait in **Admin → Waiting for approval**, and the admin digest e‑mail lists them.

## Fields, categories and sub-disciplines

Three levels, stored in the database and edited in **Admin → Fields & disciplines**:

- **Fields:** Music and Sound, Theatre, Cinema, Dance and Performance.
- **Categories** inside each field, e.g. *Music and Sound → Spatial audio*. A category can also be **shared by all fields**; *Format & context* (research, paper, workshop, premiere, mobility…) is shared and appears under every field.
- **Sub-disciplines** inside each category, e.g. *ambisonics*. These are what an entry is tagged with.

An entry automatically belongs to the fields of its sub-disciplines. More fields can be ticked by hand, and an entry is never left without a field (default: Music and Sound).

In the editor you can rename anything (LT/EN), change colours (a hue 0–359) and order, and add or remove items. **Keys** (e.g. `filmmusic`) are what entries store and can't be changed. Deleting is safe:

- **Field:** its categories move to another field or become shared, and its entries move to the target field.
- **Category:** its sub-disciplines move to another category.
- **Sub-discipline:** it's removed from entries, or replaced by another one, which also works as a merge.

The existing 278 entries were all assigned to Music and Sound. Theatre, Cinema or Dance were added only where the title said so unmistakably (opera and music‑theatre calls; film‑music and cinema calls; dance culture). To let Claude review all entries and add the other fields where they really belong, run once on the server:

```bash
sudo -u opencalls env FLASK_APP=wsgi.py .venv/bin/flask classify-fields --dry-run   # see the suggestions
sudo -u opencalls env FLASK_APP=wsgi.py .venv/bin/flask classify-fields             # apply (adds only, logged per entry)
```

New entries get their fields and sub-disciplines from Claude when added by link. Claude chooses from the current tree, so anything an admin adds is used straight away.

## E-mail notifications (SMTP)

The daily job (`flask send-notifications`, 09:00) sends **at most one e‑mail per person per day**, bundling:

| What | When |
|---|---|
| Deadline reminders for subscribed calls | first when the deadline is **30 days** away, then **every 7 days** until it (`REMINDER_FIRST_DAYS`, `REMINDER_EVERY_DAYS`) |
| New calls in followed series | the day after a call of the series is published or approved |
| Changes to subscribed calls | e.g. a deadline extension found by the weekly check, or changed by an admin |
| Admin digest (admins only) | entries newly waiting for approval or review |

**Admin → E‑mails** lists every e‑mail the app sent or tried to send: recipient, subject, type, status (*sent*, *failed* with the server's reason, or *log only* when SMTP isn't configured) and the text. Failed connections to the mail server are recorded too. Entries older than a year are removed automatically. **Admin → E‑mails → Send a test e‑mail** shows the current SMTP settings (without the password) and sends a simple test, a preview of a user's daily e‑mail, or a preview of the admin digest. Previews are marked [TEST] and change nothing.

Users choose what they receive under **My subscriptions → E‑mail notifications**. Each e‑mail has a one‑click "stop all e‑mails" link and a `List-Unsubscribe` header. Language follows the user's LT/EN choice.

**Sending:** MailerLite itself has no SMTP. Its transactional sister product **MailerSend** has it, and you log in with your MailerLite account (single sign‑on). In MailerSend:

1. **Domains → Add domain**, e.g. `misc.lmta.lt`. Add the DNS records it shows (SPF, DKIM, return path) at LMTA's DNS; that needs LMTA IT. Wait until the domain shows as verified.
2. **Domains → (your domain) → SMTP → Generate new user.** Copy the username and password.
3. In `/var/www/open-calls/.env`:
   ```
   SMTP_HOST=smtp.mailersend.net
   SMTP_PORT=587
   SMTP_USERNAME=…
   SMTP_PASSWORD=…
   MAIL_FROM=MISC Open Calls <noreply@misc.lmta.lt>
   ```
4. Run `sudo systemctl restart opencalls`, then send a test: `sudo -u opencalls env FLASK_APP=wsgi.py .venv/bin/flask mail-test you@lmta.lt`.

Any SMTP server works with the same settings. For example, LMTA's Microsoft 365: `SMTP_HOST=smtp.office365.com`, port 587, a mailbox with SMTP AUTH enabled by IT, and `MAIL_FROM` set to that mailbox. Without `SMTP_HOST`, e‑mails are only written to the log (`journalctl -u opencalls-reminders`).

## Production deployment — https://misc.lmta.lt/open-calls

No Docker or containers: it is a plain Flask app served by **gunicorn**, managed by **systemd**, behind the existing **nginx**. It runs next to WordPress and the other apps on misc.lmta.lt (museum, ARJournal, journal, booking, kimo, tension…).

**Layout:** the git clone **is** the installed app, in `/var/www/open-calls`.

| Path | Owner / mode | Why |
|---|---|---|
| `/var/www/open-calls` (code, `.venv`) | you (the user who runs `git pull`) | You update with `git pull`; the app can read its code but not modify it |
| `.env` (git‑ignored) | you, group `opencalls`, 640 | The settings file; the service can read it, other users can't |
| `instance/` (SQLite database) | `opencalls`, 750 | The only place the app writes |

- The service runs as the system user `opencalls`. Gunicorn listens on a **unix socket**, `/run/opencalls/gunicorn.sock` (`opencalls:www-data`), not on a TCP port, so it cannot clash with the other apps' ports.
- `/etc/nginx/snippets/misc-open-calls.conf` is included in the HTTPS `server {}` block right after `server_name`, next to `lmta-museum.conf`. It forwards `/open-calls/` to the socket and sends `X-Forwarded-Prefix`, so every link, redirect and cookie stays under `/open-calls`. Its `^~` locations take priority over the regex rules in that block (`\.php$`, the static-file caching rule, `~ /booking(.*)`) and don't touch any other path.

### First installation

```bash
sudo git clone https://github.com/iorobertob/open-calls.git /var/www/open-calls
sudo chown -R "$(whoami)": /var/www/open-calls
cd /var/www/open-calls
cp .env.example .env && nano .env        # MS_*, ADMIN_EMAILS, MAILERLITE_*, ANTHROPIC_API_KEY
./deploy/deploy.sh
```

### Every update

Push from your computer, then on the server:

```bash
cd /var/www/open-calls
git pull
./deploy/deploy.sh
```

Run `deploy.sh` as yourself, not with sudo. It refuses to run as root and asks for sudo itself. It runs `deploy/install.sh`, which is idempotent:

- creates the `opencalls` system user (once)
- applies the production values in `.env`: `DEV_LOGIN=0`, `APP_PREFIX=/open-calls`, `PUBLIC_BASE_URL`, HTTPS cookies, and a strong `SECRET_KEY` if missing; everything else in `.env` is left as you wrote it
- sets the permissions in the table above
- creates/updates the virtualenv (as you), runs database migrations (as `opencalls`), and seeds the curated list the first time only
- installs `opencalls.service` plus the **weekly refresh** (Monday 03:15) and **daily e‑mail** (09:00) timers, then reloads gunicorn gracefully (no downtime)
- writes the nginx snippet and, the first time only, adds its `include` to the `listen 443` block for misc.lmta.lt (the port‑80 redirect block is left alone). A backup goes to `/var/backups/opencalls-nginx/`; if `nginx -t` fails, the site file and snippet are restored
- reloads nginx and checks that `https://misc.lmta.lt/open-calls/` returns 200

Nothing in the clone is copied or deleted, and `git status` stays clean.

Server requirements: a user with sudo, git, Python 3.10 or newer with `venv`, and `curl`. If the site's nginx file cannot be found automatically, pass `NGINX_SITE=/etc/nginx/sites-available/<file>`. In the Entra app registration, the redirect URIs are `https://misc.lmta.lt/open-calls/auth/callback` (login) and `https://misc.lmta.lt/open-calls/` (after logout).

### Moving from the earlier (copied) layout

The first version of the deploy script copied the code into `/var/www/open-calls` without `.git`. To switch to the clone layout, keeping the database and settings:

```bash
sudo systemctl stop opencalls
sudo mv /var/www/open-calls /var/www/open-calls.old
sudo git clone https://github.com/iorobertob/open-calls.git /var/www/open-calls
sudo chown -R "$(whoami)": /var/www/open-calls
sudo cp -a /var/www/open-calls.old/instance /var/www/open-calls/
sudo cp /var/www/open-calls.old/.env /var/www/open-calls/.env
cd /var/www/open-calls && ./deploy/deploy.sh
# check the site, then: sudo rm -rf /var/www/open-calls.old
```

### Automatic deployment (push to main)

`.github/workflows/deploy.yml` runs the tests on GitHub, then deploys. The server is behind the VPN, so
GitHub cannot connect to it: a **self-hosted GitHub Actions runner** on the server opens an *outgoing*
connection to GitHub, picks up the deploy job and runs `git fetch` + `git merge --ff-only` + `./deploy/deploy.sh`
in `/var/www/open-calls`, as the owner of the clone.

One-time setup on the server (as the owner of the clone):

1. A sudo rule so the deploy runs without a password — only this exact command:
   `sudo visudo -f /etc/sudoers.d/opencalls-deploy` →
   `<you> ALL=(root) NOPASSWD:SETENV: /usr/bin/bash /var/www/open-calls/deploy/install.sh`
2. The runner: GitHub → repository → Settings → Actions → Runners → *New self-hosted runner* (Linux x64);
   follow the download commands in `~/actions-runner`, then
   `./config.sh --url https://github.com/iorobertob/open-calls --token <token> --name misc-server --labels open-calls --unattended`
   and `sudo ./svc.sh install "$(whoami)" && sudo ./svc.sh start`.

Runner logs: `journalctl -u 'actions.runner.*' -f`. Redeploy without a commit: Actions → *Test and deploy* → *Run workflow*.
If files were edited by hand on the server, the fast-forward stops the deploy instead of overwriting them.

## Operations on the server

Everything runs under systemd. There are no containers.

| Unit | What it is |
|---|---|
| `opencalls.service` | The web app (gunicorn, socket `/run/opencalls/gunicorn.sock`). Restarts automatically if it crashes (`Restart=on-failure`) and starts on boot. |
| `opencalls-refresh.timer` → `opencalls-refresh.service` | **Weekly, Monday 03:15** (Vilnius): archive expired entries, translate, re‑check current calls' pages, scan series pages, keep expected‑next placeholders |
| `opencalls-reminders.timer` → `opencalls-reminders.service` | Daily 09:00 (Vilnius): e‑mails — deadline reminders, series news, changes, admin digest |

Code: `/var/www/open-calls` · settings: `/var/www/open-calls/.env` · database: `/var/www/open-calls/instance/opencalls.db` · nginx: `/etc/nginx/snippets/misc-open-calls.conf`

**Is it running? Restart it**

```bash
sudo systemctl status opencalls            # running? last log lines
sudo systemctl restart opencalls           # full restart (a second of downtime)
sudo systemctl reload opencalls            # graceful: new workers, no downtime (after code changes)
sudo systemctl start opencalls             # if it is stopped
```

**If the site shows "502 Bad Gateway"**, the app is not answering. Work through these in order:

```bash
sudo systemctl status opencalls                       # failed? read the error at the bottom
sudo journalctl -u opencalls -n 100 --no-pager        # full error (e.g. a bad .env value, missing package)
ls -l /run/opencalls/gunicorn.sock                     # should exist, owner opencalls:www-data
curl -s --unix-socket /run/opencalls/gunicorn.sock http://localhost/about -o /dev/null -w '%{http_code}\n'   # 200 = app OK
sudo systemctl restart opencalls
```

If the app answers 200 on the socket but the site still fails, the problem is in nginx. Run `sudo nginx -t`, and check that the HTTPS server block still contains `include /etc/nginx/snippets/misc-open-calls.conf;`. Then `sudo systemctl reload nginx`. After a crash loop, systemd may refuse to start the service again ("start request repeated too quickly"). Run `sudo systemctl reset-failed opencalls`, then start it.

**Logs**

```bash
sudo journalctl -u opencalls -f                  # live app log (requests, login errors)
sudo journalctl -u opencalls-refresh -n 50       # last refresh run
sudo journalctl -u opencalls-reminders -n 50     # last e-mail run
systemctl list-timers 'opencalls-*'              # when the jobs run next / ran last
```

**Run the daily jobs now**

```bash
sudo systemctl start opencalls-refresh       # refresh now (output in its journal)
sudo systemctl start opencalls-reminders     # send today's e-mails now
```

**Run any `flask` command on the server** (as the app user, so file permissions stay correct):

```bash
cd /var/www/open-calls
sudo -u opencalls env FLASK_APP=wsgi.py .venv/bin/flask send-notifications --dry-run
sudo -u opencalls env FLASK_APP=wsgi.py .venv/bin/flask translate --dry-run
sudo -u opencalls env FLASK_APP=wsgi.py .venv/bin/flask make-admin someone@lmta.lt
```

**Change a setting.** Edit `/var/www/open-calls/.env` on the server (it's yours, no sudo needed), then `sudo systemctl restart opencalls`. Use restart, not reload: systemd reads `.env` only when the service starts. Your local `.env` is only for running the app on your computer; it is never uploaded.

**Back up the database.** SQLite is a single file. Copy it safely while the app is running:

```bash
cd /var/www/open-calls
sudo -u opencalls .venv/bin/python -c "import sqlite3,datetime; s=sqlite3.connect('instance/opencalls.db'); s.backup(sqlite3.connect(f'instance/backup-{datetime.date.today()}.db'))"
```

**Remove the app from the site** (WordPress and the other apps are unaffected): delete the `include /etc/nginx/snippets/misc-open-calls.conf;` line, run `sudo nginx -t && sudo systemctl reload nginx`, then `sudo systemctl disable --now opencalls opencalls-refresh.timer opencalls-reminders.timer`.

## Weekly workflow (compatibility)

The coordinator's weekly Claude routine produces `MISC-sarasas-<date>.html` with an embedded `misc-duomenys` JSON block. Upload that file in **Admin → Import weekly list** (or run `flask import`). Entries are merged by URL + title, changed fields are logged, and expired entries are skipped. The routine can also *read* the current state from `/api/export.json` instead of last week's artifact.

## Project layout

```
app/
  models.py      Call, Series, Field/Category/Discipline, CallChange (audit), User, Subscription, SeriesFollow,
                 Notification, EmailLog, RefreshRun
  taxonomy.py    default field → category → sub-discipline tree, tax() helper, types, countries
  classify.py    flask classify-fields (Claude assigns fields to existing entries)
  search.py      filters shared by the list, API, calendar exports and map
  extract.py     page fetch + Claude structured extraction + heuristic fallback
  refresh.py     weekly job: archive, translate, re-check calls (overwrite guard), scan series
  series.py      series, expected-next placeholders, series page scan, follower notifications
  notify.py      daily e-mails over SMTP (reminders, series news, changes, admin digest)
  duplicates.py  duplicate detection (same link / similar title)
  translate.py   fills missing LT/EN texts with Claude
  importer.py    weekly JSON/HTML import (upsert)
  ics.py         iCalendar generation
  auth.py        Microsoft Entra ID login (MSAL)
  views.py, admin.py, cli.py, scheduler.py
  screen_template.html   the MISC TV-screen template, filled by /screen
seed/            initial curated data
deploy/          deploy.sh (run on the server), install.sh, systemd units/timers, nginx snippet
migrations/      Alembic migrations
```
