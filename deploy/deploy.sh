#!/usr/bin/env bash
# Deploy MISC open calls to https://misc.lmta.lt/open-calls (WordPress + nginx server).
# Run from the project folder:
#
#   ./deploy/deploy.sh                # deploy / update
#   ./deploy/deploy.sh --skip-tests   # without running the test suite first
#
# Uses your .env (credentials). On the server, production-only values are applied automatically
# (DEV_LOGIN=0, HTTPS, the /open-calls prefix, a server-side SECRET_KEY) — see remote-install.sh.
#
# SSH: connects to "misc.lmta.lt" using your SSH config. If your server login is not the same as
# your local username, either add this to ~/.ssh/config:
#     Host misc.lmta.lt
#         User your-server-user
# or put DEPLOY_SSH=your-server-user@misc.lmta.lt in .env.
set -euo pipefail
cd "$(dirname "$0")/.."

DOMAIN="misc.lmta.lt"
URL_PREFIX="/open-calls"
RELEASE="opencalls-release"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

SKIP_TESTS=0
case "${1:-}" in
  --skip-tests) SKIP_TESTS=1 ;;
  -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
  "") ;;
  *) die "unknown option $1" ;;
esac

[[ -f .env ]] || die ".env not found (copy .env.example to .env and fill it in)"
TARGET=$(grep -E '^DEPLOY_SSH=' .env | tail -n1 | cut -d= -f2- || true)
TARGET="${TARGET:-$DOMAIN}"

if [[ $SKIP_TESTS -eq 0 ]]; then
  PYBIN=""
  for p in .venv/bin/python venv/bin/python; do [[ -x $p ]] && PYBIN=$p && break; done
  if [[ -n "$PYBIN" ]] && "$PYBIN" -c 'import pytest' 2>/dev/null; then
    log "running tests"
    "$PYBIN" -m pytest -q tests || die "tests failed — fix them or use --skip-tests"
  else
    log "pytest not installed locally — skipping tests"
  fi
fi

log "uploading code to $TARGET:~/$RELEASE"
rsync -az --delete \
  --exclude '.git/' --exclude '.venv/' --exclude 'venv/' --exclude 'instance/' --exclude '.env' \
  --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude '.claude/' --exclude '.DS_Store' \
  --exclude 'initial_files/' \
  ./ "$TARGET:$RELEASE/"

log "uploading .env"
ssh "$TARGET" "umask 077; cat > $RELEASE.env" < .env

# Optional overrides for unusual servers (environment variables, rarely needed):
# APP_DIR (/var/www/open-calls) APP_USER (opencalls) NGINX_SITE (auto-detected) PYTHON (python3)
PASS_VARS=""
for v in APP_DIR APP_USER NGINX_SITE PYTHON; do
  if [[ -n "${!v:-}" ]]; then PASS_VARS+=" $v=$(printf '%q' "${!v}")"; fi
done

log "installing on the server (sudo may ask for your password)"
ssh -t "$TARGET" "sudo env DOMAIN=$DOMAIN URL_PREFIX=$URL_PREFIX$PASS_VARS bash \$HOME/$RELEASE/deploy/remote-install.sh \$HOME/$RELEASE \$HOME/$RELEASE.env"

log "done → https://$DOMAIN$URL_PREFIX/"
