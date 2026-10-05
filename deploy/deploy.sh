#!/usr/bin/env bash
# Deploy / update on the server, in the git clone (normally /var/www/open-calls):
#
#   cd /var/www/open-calls
#   git pull
#   ./deploy/deploy.sh
#
# Run it as yourself (the owner of the clone), not with sudo — it asks for sudo itself for the
# install step: dependencies, database migrations, systemd, nginx, graceful reload (deploy/install.sh).
set -euo pipefail
cd "$(dirname "$0")/.."

[[ $EUID -ne 0 ]] || { echo "xx run as your normal user (the owner of $(pwd)), not as root/sudo" >&2; exit 1; }
[[ -d .git ]] || echo "!! $(pwd) is not a git clone — continuing, but updates are meant to come from git pull" >&2

sudo env DOMAIN="${DOMAIN:-misc.lmta.lt}" URL_PREFIX="${URL_PREFIX:-/open-calls}" \
  ${NGINX_SITE:+NGINX_SITE="$NGINX_SITE"} bash deploy/install.sh
