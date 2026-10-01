#!/usr/bin/env bash
# Installs / updates MISC open calls on the server. Run as root (deploy.sh calls it via sudo):
#
#   sudo bash remote-install.sh <release_dir> [uploaded .env]
#
# Idempotent: safe to re-run for every update. Settings via environment (defaults below).
set -euo pipefail

RELEASE_DIR="${1:?release dir}"
ENV_FILE="${2:-}"
APP_DIR="${APP_DIR:-/var/www/open-calls}"
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

# One deploy at a time; never leave the uploaded .env (it holds credentials) lying around.
exec 9>/run/opencalls-deploy.lock
flock -n 9 || die "another deploy is running"
trap '[[ -n "$ENV_FILE" ]] && rm -f "$ENV_FILE"' EXIT
BACKUP_DIR=/var/backups/opencalls-nginx   # outside /etc/nginx so backups are never loaded as config
mkdir -p "$BACKUP_DIR"
command -v nginx >/dev/null || die "nginx not found"
command -v rsync >/dev/null || die "rsync not found (apt install rsync)"

# ---- Python >= 3.10 (anthropic SDK 1.x requirement)
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "$PY is older than 3.10 — install a newer Python (e.g. apt install python3.12 python3.12-venv) and set PYTHON=python3.12"
"$PY" -m venv --help >/dev/null 2>&1 || die "python venv module missing (apt install python3-venv)"

# ---- service user and files
if ! id "$APP_USER" >/dev/null 2>&1; then
  log "creating system user $APP_USER"
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi
mkdir -p "$APP_DIR"
log "syncing code to $APP_DIR"
rsync -a --delete \
  --exclude '.env' --exclude 'instance/' --exclude '.venv/' --exclude '.cache/' --exclude '__pycache__/' \
  "$RELEASE_DIR"/ "$APP_DIR"/

# ---- .env: the uploaded developer .env + production overrides.
# Values that differ between your computer and the server are forced here, so one .env serves both.
# SECRET_KEY stays server-only: kept from the previous install, or generated on the first one.
OVERRIDES="DEV_LOGIN APP_PREFIX PUBLIC_BASE_URL PREFERRED_URL_SCHEME SESSION_COOKIE_SECURE SECRET_KEY DEPLOY_SSH"
if [[ -n "$ENV_FILE" ]]; then
  log "installing .env (with production overrides)"
  secret=""
  [[ -f "$APP_DIR/.env" ]] && secret=$(grep -E '^SECRET_KEY=' "$APP_DIR/.env" | tail -n1 | cut -d= -f2- || true)
  [[ -n "$secret" ]] || secret=$("$PY" -c 'import secrets; print(secrets.token_urlsafe(48))')
  tmp=$(mktemp)
  {
    grep -vE "^($(echo $OVERRIDES | tr ' ' '|'))=" "$ENV_FILE" || true
    echo
    echo "# ---- production values, set by deploy/remote-install.sh (edits above this line are yours)"
    echo "DEV_LOGIN=0"
    echo "APP_PREFIX=$URL_PREFIX"
    echo "PUBLIC_BASE_URL=https://$DOMAIN$URL_PREFIX"
    echo "PREFERRED_URL_SCHEME=https"
    echo "SESSION_COOKIE_SECURE=1"
    echo "SECRET_KEY=$secret"
  } > "$tmp"
  install -m 600 -o "$APP_USER" -g "$APP_USER" "$tmp" "$APP_DIR/.env"
  rm -f "$tmp" "$ENV_FILE"
fi
[[ -f "$APP_DIR/.env" ]] || die "$APP_DIR/.env is missing — run deploy.sh from a folder that has a .env"

mkdir -p "$APP_DIR/instance"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
# nginx (www-data) serves static files directly: directories must be traversable
chmod 755 "$APP_DIR" "$APP_DIR/app"
find "$APP_DIR/app/static" -type d -exec chmod 755 {} + ; find "$APP_DIR/app/static" -type f -exec chmod 644 {} +
chmod 700 "$APP_DIR/instance"

# ---- virtualenv, dependencies, database
as_app() { sudo -u "$APP_USER" -H env FLASK_APP=wsgi.py "$@"; }
cd "$APP_DIR"
[[ -x .venv/bin/python ]] || { log "creating virtualenv"; as_app "$PY" -m venv .venv; }
log "installing Python dependencies"
as_app .venv/bin/pip install -q --upgrade pip
as_app .venv/bin/pip install -q -r requirements.txt
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
