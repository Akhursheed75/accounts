#!/usr/bin/env bash
# ===========================================================================
# Reconcilia — put a domain and a real certificate in front of the site.
#
#   sudo ./enable-https.sh account.example.com
#   sudo ./enable-https.sh account.example.com you@example.com
#
# Adds Caddy to the stack, which obtains and renews a Let's Encrypt
# certificate on its own, and moves the plain-HTTP port so that it can only
# be reached from the server itself.
#
# If anything fails, it puts everything back the way it was.
# ===========================================================================
set -euo pipefail

DOMAIN=""
ACME_EMAIL=""
SKIP_DNS=false
for arg in "$@"; do
  case "$arg" in
    --skip-dns-check) SKIP_DNS=true ;;
    -h|--help) sed -n '3,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "Unknown option: $arg" >&2; exit 1 ;;
    *@*) ACME_EMAIL="$arg" ;;
    *) [[ -z "$DOMAIN" ]] && DOMAIN="$arg" ;;
  esac
done

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -t 1 ]]; then
  BOLD=$'\e[1m'; DIM=$'\e[2m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RED=$'\e[31m'; OFF=$'\e[0m'
else
  BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; OFF=""
fi
step() { echo; echo "${BOLD}==> $*${OFF}"; }
ok()   { echo "    ${GREEN}✓${OFF} $*"; }
warn() { echo "    ${YELLOW}!${OFF} $*"; }
die()  { echo; echo "${RED}✗ $*${OFF}" >&2; exit 1; }

[[ -n "$DOMAIN" ]] || die "Usage: sudo ./enable-https.sh your.domain.com [you@example.com]"
[[ -f docker-compose.yml && -f .env ]] \
  || die "Run this from the reconcilia directory, after server-setup.sh has finished."

if [[ $EUID -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || die "This script needs root."
  exec sudo -E bash "$0" "$@"
fi

[[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$ ]] \
  || die "'$DOMAIN' does not look like a domain name."

echo "${BOLD}Enabling HTTPS for ${DOMAIN}${OFF}"

# --- helpers ---------------------------------------------------------------
env_get() {
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" .env | tail -n 1 \
    | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

env_set() {
  python3 - "$1" "$2" <<'PY'
import re, sys, pathlib
key, value = sys.argv[1], sys.argv[2]
path = pathlib.Path(".env")
lines = path.read_text().splitlines()
pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
replaced = False
out = []
for line in lines:
    if pattern.match(line):
        out.append(f"{key}={value}")
        replaced = True
    else:
        out.append(line)
if not replaced:
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n")
PY
}

# --- 1. DNS ----------------------------------------------------------------
step "Checking DNS"
SERVER_IP=$(curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
RESOLVED=$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1}' | sort -u | paste -sd, - || true)
echo "    this server: ${SERVER_IP}"
echo "    ${DOMAIN}: ${RESOLVED:-no answer}"
if [[ "$SKIP_DNS" != true ]]; then
  [[ -n "$RESOLVED" ]] || die "$DOMAIN does not resolve yet.
    Add an A record pointing it at ${SERVER_IP}, give it a few minutes, then run this again."
  if [[ ",$RESOLVED," != *",$SERVER_IP,"* ]]; then
    die "$DOMAIN points at ${RESOLVED}, not at this server (${SERVER_IP}).
    Fix the A record first — Let's Encrypt will refuse, and it rate-limits failures.
    If something in front hides this server's real address, re-run with --skip-dns-check."
  fi
fi
ok "DNS points here"

# --- 2. email --------------------------------------------------------------
if [[ -z "$ACME_EMAIL" ]]; then
  ACME_EMAIL=$(env_get ACME_EMAIL)
  [[ -z "$ACME_EMAIL" ]] && ACME_EMAIL=$(env_get ADMIN_EMAIL)
fi
[[ -n "$ACME_EMAIL" ]] \
  || die "No email address for the certificate. Pass one:
    sudo ./enable-https.sh $DOMAIN you@example.com"
echo "    expiry notices to ${ACME_EMAIL}"

# --- 3. back everything up -------------------------------------------------
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=".https-backup-$STAMP"
mkdir -p "$BACKUP_DIR"
cp .env "$BACKUP_DIR/.env"
cp docker-compose.yml "$BACKUP_DIR/docker-compose.yml"
cp nginx/reconcilia.conf "$BACKUP_DIR/reconcilia.conf"
ok "Current configuration saved in $BACKUP_DIR"

rollback() {
  warn "Putting the previous configuration back"
  cp "$BACKUP_DIR/.env" .env
  cp "$BACKUP_DIR/docker-compose.yml" docker-compose.yml
  cp "$BACKUP_DIR/reconcilia.conf" nginx/reconcilia.conf
  rm -f docker-compose.https.yml
  docker compose up -d --remove-orphans >/dev/null 2>&1 || true
  echo
  echo "    The site is back on plain HTTP at http://${SERVER_IP}"
}

# Something else on this machine holding port 80 means Caddy cannot bind it, and
# that something is most likely host nginx put there by server-setup.sh --domain,
# which already does this job.
if ss -ltn 2>/dev/null | grep -qE '(^|[^0-9.:])(0\.0\.0\.0|\[::\]|\*):80\b' \
   && ! docker compose ps --services --filter status=running 2>/dev/null | grep -qx proxy; then
  die "Something on this server is already listening on port 80.
If that is nginx from './server-setup.sh --domain', HTTPS is already set up and
you do not need this script. Otherwise stop it first."
fi

# --- 4. the plain-HTTP port becomes local-only -----------------------------
step "Moving the plain-HTTP port"
python3 - <<'PY'
import pathlib, re, sys
path = pathlib.Path("docker-compose.yml")
text = path.read_text()
# Caddy needs port 80 on the host. nginx keeps a port, but bound to loopback,
# so the application can no longer be reached over an unencrypted connection.
line = '      - "${HTTP_BIND:-127.0.0.1}:${HTTP_PORT:-8080}:80"'
patched, count = re.subn(r'^ *- *"\$\{HTTP_BIND[^"]*"$', line, text, flags=re.M)
if count == 0:
    patched, count = re.subn(r'^ *- *"\$\{HTTP_PORT[^"]*"$', line, text, flags=re.M)
if count == 0:
    sys.exit("could not find the proxy port mapping in docker-compose.yml")
path.write_text(patched)
PY
env_set HTTP_BIND "127.0.0.1"
env_set HTTP_PORT "8080"
ok "nginx will listen on 127.0.0.1:8080 only"

# --- 5. nginx should trust the scheme Caddy reports ------------------------
if ! grep -q 'forwarded_scheme' nginx/reconcilia.conf; then
  python3 - <<'PY'
import pathlib
path = pathlib.Path("nginx/reconcilia.conf")
text = path.read_text()
prelude = """# When something terminates TLS in front of this container, its
# X-Forwarded-Proto is the truth; $scheme here would always say "http".
map $http_x_forwarded_proto $forwarded_scheme {
    default $scheme;
    ~.      $http_x_forwarded_proto;
}

"""
text = prelude + text.replace(
    "proxy_set_header X-Forwarded-Proto $scheme;",
    "proxy_set_header X-Forwarded-Proto $forwarded_scheme;",
)
path.write_text(text)
PY
  ok "nginx will pass the real scheme through"
fi

# --- 6. Caddy --------------------------------------------------------------
step "Adding Caddy"
mkdir -p caddy
cat > caddy/Caddyfile <<'CADDY'
{
	email {$ACME_EMAIL}
}

{$SITE_DOMAIN} {
	encode zstd gzip

	# Bank statements are the largest thing that crosses this proxy.
	request_body {
		max_size 30MB
	}

	reverse_proxy proxy:80 {
		header_up X-Forwarded-Proto https
	}
}
CADDY

cat > docker-compose.https.yml <<'COMPOSE'
# Terminates TLS in front of the stack. Caddy obtains the certificate on first
# start and renews it by itself, so there is no cron job to forget about.
#
# Activated by COMPOSE_FILE in .env, which means every ordinary
# `docker compose` command picks it up without extra flags.

services:
  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    depends_on:
      - proxy
    environment:
      SITE_DOMAIN: ${SITE_DOMAIN:?set SITE_DOMAIN in .env}
      ACME_EMAIL: ${ACME_EMAIL:?set ACME_EMAIL in .env}
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    volumes:
      - ./caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      # The certificate and the ACME account key live here. Losing this volume
      # means asking Let's Encrypt for a new certificate, which is rate-limited.
      - caddy-data:/data
      - caddy-config:/config

volumes:
  caddy-data:
  caddy-config:
COMPOSE

env_set SITE_DOMAIN "$DOMAIN"
env_set ACME_EMAIL "$ACME_EMAIL"
env_set COMPOSE_FILE "docker-compose.yml:docker-compose.https.yml"
env_set COOKIE_SECURE "true"
env_set CORS_ORIGINS "https://$DOMAIN"
ok "Configuration written"

# --- 7. firewall -----------------------------------------------------------
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
  ok "Ports 80 and 443 allowed through ufw"
fi

# --- 8. restart ------------------------------------------------------------
step "Restarting"
if ! docker compose up -d --remove-orphans; then
  rollback
  die "Compose could not start the new configuration. Nothing has been changed."
fi

if ! docker compose ps --services 2>/dev/null | grep -qx caddy; then
  rollback
  die "The caddy service did not start — this build of Compose may not read COMPOSE_FILE from .env.
    Start it explicitly instead:
      docker compose -f docker-compose.yml -f docker-compose.https.yml up -d"
fi
ok "Caddy is running"

# --- 9. prove it works -----------------------------------------------------
step "Waiting for the certificate"
echo "    ${DIM}Let's Encrypt usually answers within half a minute.${OFF}"
HTTPS_OK=false
for _ in $(seq 1 40); do
  if curl -fsS --max-time 8 "https://${DOMAIN}/api/health" 2>/dev/null | grep -q '"status":"ok"'; then
    HTTPS_OK=true
    break
  fi
  printf '.'
  sleep 5
done
echo

if [[ "$HTTPS_OK" != true ]]; then
  echo
  echo "${RED}HTTPS is not answering.${OFF} The last 30 lines from Caddy:"
  docker compose logs --tail 30 caddy || true
  echo
  read -r -p "    Put the previous plain-HTTP configuration back? [Y/n] " REPLY_ROLL
  if [[ "${REPLY_ROLL:-Y}" =~ ^[Yy]?$ ]]; then
    rollback
    die "Rolled back. Fix whatever the log above reports, then run this again."
  fi
  die "Left as it is. Watch it with:  docker compose logs -f caddy"
fi
ok "https://${DOMAIN} is serving a valid certificate"

CERT_INFO=$(echo | openssl s_client -servername "$DOMAIN" -connect "$DOMAIN:443" 2>/dev/null \
            | openssl x509 -noout -issuer -enddate 2>/dev/null || true)
[[ -n "$CERT_INFO" ]] && echo "$CERT_INFO" | sed 's/^/    /'

cat <<EOF

${GREEN}${BOLD}HTTPS is on.${OFF}

  ${BOLD}https://${DOMAIN}${OFF}

  Session cookies are now marked secure, so a browser will never send one over
  an unencrypted connection. http:// on that domain redirects to https://.

  The site is deliberately no longer reachable at http://${SERVER_IP} — nginx
  listens on 127.0.0.1:8080, where only this server can reach it.

  Caddy renews the certificate by itself. There is nothing to schedule.

${BOLD}Everything else is unchanged${OFF}
  docker compose logs -f api worker caddy
  ./backup.sh
  sudo ./server-setup.sh --update

${BOLD}To undo this${OFF}
  cp ${BACKUP_DIR}/.env ${BACKUP_DIR}/docker-compose.yml .
  cp ${BACKUP_DIR}/reconcilia.conf nginx/reconcilia.conf
  rm docker-compose.https.yml
  docker compose up -d --remove-orphans
EOF
