#!/usr/bin/env bash
# Installs / updates MISC open calls IN PLACE, in the git clone this script belongs to
# (normally /var/www/open-calls). Run as root — deploy/deploy.sh does it for you:
#
#   cd /var/www/open-calls && git pull && ./deploy/deploy.sh
#
# Layout:  the clone (code, .venv) belongs to you (the user who runs `git pull`);
#          the service user `opencalls` only reads the code and writes instance/ (the database);
#          .env is yours, readable by the service (mode 640), never by other users.
# Idempotent: safe to re-run for every update. Nothing in the clone is copied or deleted.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"
APP_USER="${APP_USER:-opencalls}"
SOCKET=/run/opencalls/gunicorn.sock   # systemd RuntimeDirectory (see opencalls.service)
URL_PREFIX="${URL_PREFIX:-/open-calls}"
DOMAIN="${DOMAIN:-misc.lmta.lt}"
NGINX_SITE="${NGINX_SITE:-}"          # auto-detected when empty
SNIPPET=/etc/nginx/snippets/misc-open-calls.conf

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root (sudo)"

# One deploy at a time
exec 9>/run/opencalls-deploy.lock
flock -n 9 || die "another deploy is running"
BACKUP_DIR=/var/backups/opencalls-nginx   # outside /etc/nginx so backups are never loaded as config
mkdir -p "$BACKUP_DIR"
command -v nginx >/dev/null || die "nginx not found"
[[ -f "$APP_DIR/wsgi.py" && -d "$APP_DIR/app" ]] || die "$APP_DIR does not look like the open-calls repository"
OWNER="$(stat -c %U "$APP_DIR")"
[[ "$OWNER" != root ]] || warn "$APP_DIR belongs to root — better: sudo chown -R <you>: $APP_DIR (so you can git pull without sudo)"

# ---- Python >= 3.10 (anthropic SDK 1.x requirement)
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "$PY is older than 3.10 — install a newer Python (e.g. apt install python3.12 python3.12-venv) and set PYTHON=python3.12"
"$PY" -m venv --help >/dev/null 2>&1 || die "python venv module missing (apt install python3-venv)"

# ---- service user
if ! id "$APP_USER" >/dev/null 2>&1; then
  log "creating system user $APP_USER"
  useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$APP_USER"
fi
cd "$APP_DIR"
as_owner() { sudo -u "$OWNER" -H "$@"; }
as_app()   { sudo -u "$APP_USER" env HOME=/tmp FLASK_APP=wsgi.py "$@"; }

# ---- .env: kept in the clone (git-ignored). Production values are enforced, everything else is yours.
if [[ ! -f .env ]]; then
  warn "no .env — creating one from .env.example; fill in the credentials (MS_*, MAILERLITE_*, ANTHROPIC_API_KEY) and run this again"
  install -m 640 -o "$OWNER" -g "$APP_USER" .env.example .env
fi
set_env() {   # set_env KEY VALUE — replace the line if present, append otherwise
  local key="$1" val="$2"
  if grep -qE "^$key=" .env; then
    [[ "$(grep -E "^$key=" .env | tail -n1 | cut -d= -f2-)" == "$val" ]] && return 0
    local t; t=$(mktemp)
    awk -v k="$key" -v v="$val" 'index($0, k "=") == 1 { print k "=" v; next } { print }' .env > "$t"
    cat "$t" > .env; rm -f "$t"      # cat keeps the file's owner and mode
  else
    printf '%s=%s\n' "$key" "$val" >> .env
  fi
  log ".env: $key set for production"
}
set_env DEV_LOGIN 0
set_env APP_PREFIX "$URL_PREFIX"
set_env PUBLIC_BASE_URL "https://$DOMAIN$URL_PREFIX"
set_env PREFERRED_URL_SCHEME https
set_env SESSION_COOKIE_SECURE 1
secret=$(grep -E '^SECRET_KEY=' .env | tail -n1 | cut -d= -f2- || true)
if [[ ${#secret} -lt 32 || "$secret" == change-me* || "$secret" == dev-change-me* ]]; then
  set_env SECRET_KEY "$("$PY" -c 'import secrets; print(secrets.token_urlsafe(48))')"
fi

# ---- permissions (see header): code readable by everyone incl. nginx; .env and instance/ private
find "$APP_DIR" \( -path "$APP_DIR/instance" -o -path "$APP_DIR/.env" -o -path "$APP_DIR/.git" \) -prune \
     -o -exec chmod a+rX {} +
chown "$OWNER:$APP_USER" .env && chmod 640 .env
mkdir -p instance
chown -R "$APP_USER:$APP_USER" instance && chmod 750 instance

# ---- virtualenv, dependencies, database
# the virtualenv belongs to the code owner; the service only reads/executes it
[[ -x .venv/bin/python ]] || { log "creating virtualenv"; as_owner "$PY" -m venv .venv; }
log "installing Python dependencies"
as_owner .venv/bin/pip install -q --upgrade pip
as_owner .venv/bin/pip install -q -r requirements.txt
chmod -R a+rX .venv
log "migrating database"
as_app .venv/bin/flask db upgrade
# Seed the curated list exactly once (a marker, so an emptied database is never re-seeded)
if [[ ! -f instance/.seeded ]]; then
  as_app .venv/bin/flask init-db
  as_app touch instance/.seeded
fi

# ---- systemd
render() { sed -e "s#__APP_DIR__#$APP_DIR#g" -e "s#__APP_USER__#$APP_USER#g" \
               -e "s#__SOCKET__#$SOCKET#g" -e "s#__URL_PREFIX__#$URL_PREFIX#g" "$1"; }
log "installing systemd units"
tzfix=(cat)
if [[ ! -e /usr/share/zoneinfo/Europe/Vilnius ]]; then
  warn "no tzdata for Europe/Vilnius (apt install tzdata) — timers use the server's local time"
  tzfix=(sed 's/ Europe\/Vilnius$//')
fi
unit_changed=0
for unit in opencalls.service opencalls-refresh.service opencalls-refresh.timer \
            opencalls-reminders.service opencalls-reminders.timer; do
  tmpu=$(mktemp); render "deploy/$unit" | "${tzfix[@]}" > "$tmpu"
  if ! cmp -s "$tmpu" "/etc/systemd/system/$unit"; then
    install -m 644 "$tmpu" "/etc/systemd/system/$unit"; unit_changed=1
  fi
  rm -f "$tmpu"
done
systemctl daemon-reload   # always: also recovers from a deploy interrupted right after writing units
systemctl enable --now opencalls-refresh.timer opencalls-reminders.timer >/dev/null
systemctl enable opencalls.service >/dev/null
if [[ $unit_changed -eq 0 ]] && systemctl is-active --quiet opencalls.service; then
  log "reloading gunicorn gracefully (no downtime)"
  systemctl reload opencalls.service      # HUP: new workers with the new code, old ones finish requests
  sleep 3
else
  systemctl restart opencalls.service
fi

log "waiting for gunicorn on $SOCKET"
for i in {1..20}; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --unix-socket "$SOCKET" "http://localhost/about" || true)
  [[ "$code" == 200 ]] && break
  sleep 1
done
[[ "$code" == 200 ]] || { journalctl -u opencalls -n 40 --no-pager; die "app did not start (HTTP $code)"; }

# ---- nginx: snippet + include inside the WordPress server block
log "installing nginx snippet $SNIPPET"
mkdir -p /etc/nginx/snippets
snippet_backup=""
new_snippet=$(mktemp)
render deploy/nginx-open-calls.conf > "$new_snippet"
if [[ -f "$SNIPPET" ]] && cmp -s "$new_snippet" "$SNIPPET"; then
  rm -f "$new_snippet"            # unchanged: nothing to write or back up
else
  if [[ -f "$SNIPPET" ]]; then
    snippet_backup="$BACKUP_DIR/misc-open-calls.conf.$(date +%Y%m%d%H%M%S)"
    cp -p "$SNIPPET" "$snippet_backup"
  fi
  install -m 644 "$new_snippet" "$SNIPPET"
  rm -f "$new_snippet"
fi
restore_snippet() {
  if [[ -n "$snippet_backup" ]]; then cp -p "$snippet_backup" "$SNIPPET"; else rm -f "$SNIPPET"; fi
}

if [[ -z "$NGINX_SITE" ]]; then
  NGINX_SITE=$(grep -lE "server_name[^;]*[[:space:]]$DOMAIN([[:space:]]|;)" \
                 /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf 2>/dev/null | head -n1 || true)
  [[ -n "$NGINX_SITE" ]] || die "no nginx server block with server_name $DOMAIN found — set NGINX_SITE=/path/to/site.conf"
fi
NGINX_SITE=$(readlink -f "$NGINX_SITE")
log "nginx site: $NGINX_SITE"

# idempotent: only added when no include of the snippet exists yet (any spacing)
if ! grep -qE "^[^#]*include[[:space:]]+$SNIPPET[[:space:]]*;" "$NGINX_SITE"; then
  backup="$BACKUP_DIR/$(basename "$NGINX_SITE").$(date +%Y%m%d%H%M%S)"
  cp -p "$NGINX_SITE" "$backup"
  log "adding include to the HTTPS server block for $DOMAIN (backup: $backup)"
  # after `server_name` in the block that has `listen 443` (the port-80 redirect block is left alone)
  newsite=$(mktemp); rc=0; "$PY" deploy/nginx_include.py "$backup" "$DOMAIN" "$SNIPPET" > "$newsite" || rc=$?
  if [[ $rc -ne 0 ]]; then
    rm -f "$newsite"; restore_snippet
    die "no 'listen 443' server block with server_name $DOMAIN in $NGINX_SITE — add 'include $SNIPPET;' manually"
  fi
  cat "$newsite" > "$NGINX_SITE"   # keeps the file's owner/permissions
  rm -f "$newsite"
  if ! nginx -t 2>/tmp/opencalls-nginx-test; then
    cat /tmp/opencalls-nginx-test >&2
    cp -p "$backup" "$NGINX_SITE"
    restore_snippet
    die "nginx config test failed — original restored. Add 'include $SNIPPET;' manually inside the HTTPS server block."
  fi
else
  nginx -t 2>/tmp/opencalls-nginx-test || { cat /tmp/opencalls-nginx-test >&2; restore_snippet; die "nginx config test failed — previous snippet restored"; }
fi
systemctl reload nginx

# ---- smoke test through nginx
# (nginx reload returns before the new workers take over — retry for a few seconds)
for i in {1..10}; do
  code=$(curl -sk -o /dev/null -w '%{http_code}' --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN$URL_PREFIX/" || true)
  [[ "$code" == 200 ]] && break
  sleep 1
done
if [[ "$code" == 200 ]]; then
  log "OK: https://$DOMAIN$URL_PREFIX/ answers 200"
else
  warn "https://$DOMAIN$URL_PREFIX/ answered HTTP $code — check the include is in the HTTPS (listen 443) server block"
fi
systemctl list-timers 'opencalls-*' --no-pager | head -n 4
