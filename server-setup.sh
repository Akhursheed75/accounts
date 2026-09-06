#!/usr/bin/env bash
# ===========================================================================
# Reconcilia — one-command installer, run ON the server.
#
#   sudo ./server-setup.sh --domain account.example.com
#         Everything: Docker, the application, nginx in front of it, a
#         Let's Encrypt certificate, the HTTP-to-HTTPS redirect, and the
#         cookie settings that go with being on HTTPS. Point the domain's
#         A record at this server first.
#
#   sudo ./server-setup.sh
#         The application only, served over plain HTTP on this server's IP.
#
#   sudo ./server-setup.sh --update
#         Rebuild and restart after a code change. Keeps all data, and keeps
#         the certificate and the nginx configuration.
#
#   sudo ./server-setup.sh --demo
#         Also load demo shops, sheets and the sample statements.
#
#   --email you@example.com   contact address for the certificate
#                             (defaults to the administrator address)
#
# Safe to run more than once. It never overwrites an existing .env, and it
# never touches the database volume.
# ===========================================================================
set -euo pipefail

WITH_DEMO=false
UPDATE_ONLY=false
DOMAIN=""
LE_EMAIL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --demo)     WITH_DEMO=true ;;
    --update)   UPDATE_ONLY=true ;;
    --domain)   DOMAIN="${2:-}"; shift ;;
    --domain=*) DOMAIN="${1#*=}" ;;
    --email)    LE_EMAIL="${2:-}"; shift ;;
    --email=*)  LE_EMAIL="${1#*=}" ;;
    -h|--help)
      sed -n '3,26p' "$0" | sed -e 's/^# \{0,1\}//' -e '/^===/d'
      exit 0 ;;
    *) echo "Unknown option: $1  (try --help)" >&2; exit 1 ;;
  esac
  shift
done

# A typo here would send a certificate request for the wrong name, so check the
# shape before anything else happens.
DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN%%/*}"
if [[ -n "$DOMAIN" && ! "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$ ]]; then
  echo "That does not look like a domain name: $DOMAIN" >&2
  exit 1
fi

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$PWD"

# --- presentation ----------------------------------------------------------
if [[ -t 1 ]]; then
  BOLD=$'\e[1m'; DIM=$'\e[2m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RED=$'\e[31m'; OFF=$'\e[0m'
else
  BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; OFF=""
fi
step()  { echo; echo "${BOLD}==> $*${OFF}"; }
ok()    { echo "    ${GREEN}✓${OFF} $*"; }
warn()  { echo "    ${YELLOW}!${OFF} $*"; }
die()   { echo; echo "${RED}✗ $*${OFF}" >&2; exit 1; }

echo "${BOLD}Reconcilia installer${OFF}"
echo "${DIM}Installing from $PROJECT_DIR${OFF}"

# --- 0. root ---------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    echo "Re-running with sudo…"
    exec sudo -E bash "$0" "$@"
  fi
  die "This script needs root. Run it as root, or install sudo."
fi

[[ -f docker-compose.yml ]] || die "docker-compose.yml is not here. Run this script from inside the extracted reconcilia directory."

# --- 1. swap, so the build does not run out of memory ----------------------
step "Checking memory"
TOTAL_MB=$(free -m | awk '/^Mem:/{print $2}')
SWAP_MB=$(free -m | awk '/^Swap:/{print $2}')
echo "    ${TOTAL_MB} MB RAM, ${SWAP_MB} MB swap"
if (( TOTAL_MB < 2048 && SWAP_MB < 1024 )); then
  # Compiling the frontend on a 1 GB droplet is the single most common way this
  # install fails, and it fails with a confusing "Killed" rather than an error.
  warn "Low memory. Adding a 2 GB swap file so the build can finish."
  if [[ ! -f /swapfile ]]; then
    fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
  fi
  swapon /swapfile 2>/dev/null || true
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  ok "Swap enabled"
else
  ok "Enough memory to build"
fi

# --- 2. Docker -------------------------------------------------------------
step "Checking Docker"
if ! command -v docker >/dev/null 2>&1; then
  echo "    Docker is not installed. Installing it now…"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq curl ca-certificates >/dev/null
  curl -fsSL https://get.docker.com | sh
  ok "Docker installed"
else
  ok "Docker $(docker --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "    Installing the Compose plugin…"
  apt-get update -qq
  apt-get install -y -qq docker-compose-plugin >/dev/null \
    || die "Could not install docker-compose-plugin. Install it manually and re-run."
fi
ok "Compose $(docker compose version --short 2>/dev/null || echo present)"

systemctl enable --now docker >/dev/null 2>&1 || true

# --- 3. configuration ------------------------------------------------------
step "Configuration"
PUBLIC_IP=$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null \
            || hostname -I 2>/dev/null | awk '{print $1}' \
            || echo "localhost")

# Where this stack listens on the host. On its own it takes port 80 directly.
# With a domain, nginx on this machine owns 80 and 443 and forwards to it, so
# the stack moves to a loopback-only port and cannot be reached around the
# certificate.
if [[ -n "$DOMAIN" ]]; then
  WANT_ORIGIN="https://${DOMAIN}"
  WANT_BIND="127.0.0.1"
  WANT_PORT="8080"
else
  WANT_ORIGIN="http://${PUBLIC_IP}"
  WANT_BIND="0.0.0.0"
  WANT_PORT="80"
fi

# Read and write single values in .env. Sourcing it as shell would break on any
# value containing a space, and would execute whatever a hand-edited file
# happened to contain.
env_get() {
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" .env \
    | tail -n 1 \
    | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}
env_set() {
  if grep -q "^[[:space:]]*$1[[:space:]]*=" .env; then
    sed -i "s|^[[:space:]]*$1[[:space:]]*=.*|$1=$2|" .env
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}

if [[ -f .env ]]; then
  ok ".env already exists — keeping it (delete it if you want a fresh one)"
  if grep -q "CHANGE_ME" .env; then
    die ".env still contains CHANGE_ME placeholders. Edit it, or delete it and re-run to have one generated."
  fi
else
  echo "    Generating .env with fresh random secrets…"
  DB_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)
  SECRET=$(openssl rand -hex 32)
  ADMIN_PW=$(openssl rand -base64 18 | tr -d '/+=' | head -c 20)

  # The sign-in form requires a dot in the domain, so a bare machine name like
  # "admin@vm" would create an account nobody could actually log in with.
  valid_email() { [[ "$1" =~ ^[^@[:space:]]+@[^@[:space:].]+(\.[^@[:space:].]+)+$ ]]; }

  # With a domain, an address at that domain is a sensible default and is also
  # something Let's Encrypt will accept as a contact.
  ADMIN_MAIL="${ADMIN_EMAIL:-${DOMAIN:+admin@$DOMAIN}}"
  ADMIN_MAIL="${ADMIN_MAIL:-admin@reconcilia.local}"
  if [[ -t 0 ]]; then
    while true; do
      read -r -p "    Administrator email [${ADMIN_MAIL}]: " REPLY_MAIL
      REPLY_MAIL="${REPLY_MAIL:-$ADMIN_MAIL}"
      if valid_email "$REPLY_MAIL"; then ADMIN_MAIL="$REPLY_MAIL"; break; fi
      echo "    That is not an address you could sign in with. It needs a name, an @, and a domain with a dot."
    done
  fi
  valid_email "$ADMIN_MAIL" || die "ADMIN_EMAIL '$ADMIN_MAIL' is not a valid address."

  cat > .env <<EOF
# Generated by server-setup.sh on $(date -u '+%Y-%m-%d %H:%M UTC').
# Keep this file secret. It is the key to every account and every record.

POSTGRES_USER=reconcilia
POSTGRES_PASSWORD=${DB_PASSWORD}
POSTGRES_DB=reconcilia

SECRET_KEY=${SECRET}
ENVIRONMENT=production

# Set COOKIE_SECURE=true the moment this site is served over HTTPS, then run
#   docker compose up -d
# Until then, session cookies travel in clear text.
COOKIE_SECURE=false
COOKIE_SAMESITE=lax

# The address people type in the browser. The API trusts only this origin.
CORS_ORIGINS=${WANT_ORIGIN}

# Where this stack listens on the host.
HTTP_BIND=${WANT_BIND}
HTTP_PORT=${WANT_PORT}

MAX_UPLOAD_BYTES=26214400
OCR_DPI=300
OCR_LANGUAGES=spa+eng
DEFAULT_DATE_WINDOW_DAYS=3

ADMIN_EMAIL=${ADMIN_MAIL}
ADMIN_NAME="System administrator"
ADMIN_PASSWORD=${ADMIN_PW}
EOF
  chmod 600 .env
  ok "Wrote .env (owner-readable only)"
fi

# Asking for a domain is an explicit instruction about how this server is to be
# published, so it wins over whatever an earlier run wrote.
if [[ -n "$DOMAIN" ]]; then
  CHANGED=false
  for pair in "CORS_ORIGINS=$WANT_ORIGIN" "HTTP_BIND=$WANT_BIND" "HTTP_PORT=$WANT_PORT"; do
    key="${pair%%=*}"; value="${pair#*=}"
    if [[ "$(env_get "$key")" != "$value" ]]; then
      env_set "$key" "$value"; CHANGED=true
    fi
  done
  [[ "$CHANGED" == true ]] && ok "Set CORS_ORIGINS, HTTP_BIND and HTTP_PORT for ${DOMAIN}"
fi

ADMIN_EMAIL=$(env_get ADMIN_EMAIL)
ADMIN_PASSWORD=$(env_get ADMIN_PASSWORD)
HTTP_PORT=$(env_get HTTP_PORT)
HTTP_PORT=${HTTP_PORT:-80}
CONFIGURED_ORIGIN=$(env_get CORS_ORIGINS)

# When .env names the address people actually use, that is the authoritative
# one and it is printed verbatim. HTTP_PORT is where *this* stack listens, which
# with a TLS terminator in front is an internal detail — appending it produced
# nonsense like "https://example.com:8080".
if [[ -n "$CONFIGURED_ORIGIN" ]]; then
  SITE_URL="${CONFIGURED_ORIGIN%%,*}"
else
  SITE_URL="http://${PUBLIC_IP}"
  [[ "$HTTP_PORT" != "80" ]] && SITE_URL="${SITE_URL}:${HTTP_PORT}"
fi

# Loopback-only means something else is serving the public address.
FRONTED=false
[[ "$SITE_URL" == https://* ]] && FRONTED=true
[[ "$(env_get HTTP_BIND)" == "127.0.0.1" ]] && FRONTED=true

if [[ -z "$ADMIN_EMAIL" ]]; then
  die "ADMIN_EMAIL is missing from .env. Add it and re-run."
fi

# --- 4. firewall -----------------------------------------------------------
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  step "Firewall"
  if [[ -n "$DOMAIN" ]]; then
    # nginx answers the world on 80 and 443; the stack itself is on loopback
    # only, so its port must stay closed.
    ufw allow 80/tcp  >/dev/null 2>&1 || true
    ufw allow 443/tcp >/dev/null 2>&1 || true
    ok "Ports 80 and 443 allowed through ufw"
  else
    ufw allow "${HTTP_PORT}"/tcp >/dev/null 2>&1 || true
    ok "Port ${HTTP_PORT} allowed through ufw"
  fi
fi

# --- 5. build and start ----------------------------------------------------
step "Building the application"
echo "    ${DIM}The first build compiles the frontend and installs OCR — allow 5–10 minutes.${OFF}"
docker compose build --pull

step "Starting"
docker compose up -d
ok "Containers started"

# --- 6. wait for the API ---------------------------------------------------
step "Waiting for the database migrations and the API"
API_UP=false
for _ in $(seq 1 90); do
  if docker compose exec -T api curl -fsS http://localhost:8000/api/health >/dev/null 2>&1; then
    API_UP=true; break
  fi
  printf '.'
  sleep 3
done
echo
if [[ "$API_UP" != true ]]; then
  echo
  echo "${RED}The API did not come up.${OFF} The last 40 lines of its log:"
  docker compose logs --tail 40 api
  die "Fix the problem above, then re-run:  sudo ./server-setup.sh --update"
fi
ok "API is answering"

# --- 7. seed ---------------------------------------------------------------
if [[ "$UPDATE_ONLY" == true ]]; then
  step "Update finished"
  echo "    Existing data and accounts are untouched."
else
  step "Creating reference data and the first administrator"
  if [[ "$WITH_DEMO" == true ]]; then
    docker compose exec -T api python -m app.seed --demo --with-statements
  else
    docker compose exec -T api python -m app.seed
  fi
  ok "Seed complete"

  # Assume nothing: sign in once, from inside the API container, to prove the
  # account that was just created can actually be used.
  if [[ -n "$ADMIN_PASSWORD" ]]; then
    LOGIN_BODY=$(printf '{"email":"%s","password":"%s"}' "$ADMIN_EMAIL" "$ADMIN_PASSWORD")
    if docker compose exec -T api curl -fsS -X POST \
         -H 'content-type: application/json' \
         -d "$LOGIN_BODY" \
         http://localhost:8000/api/v1/auth/login >/dev/null 2>&1; then
      ok "Signed in successfully with the new administrator account"
    else
      warn "The administrator account was created but a test sign-in failed."
      warn "Check:  docker compose logs --tail 40 api"
    fi
  fi
fi

# --- 8. domain, nginx and the certificate ----------------------------------
if [[ -n "$DOMAIN" ]]; then
  step "Publishing https://${DOMAIN}"

  # Let's Encrypt proves you control the name by connecting to it, so a domain
  # that does not resolve here cannot get a certificate. Say so now rather than
  # after a failed request, because failed requests count against a rate limit.
  RESOLVED=$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1; exit}')
  if [[ -z "$RESOLVED" ]]; then
    die "${DOMAIN} does not resolve. Add an A record pointing it at ${PUBLIC_IP}, wait a few minutes, then re-run this command."
  elif [[ "$RESOLVED" != "$PUBLIC_IP" ]]; then
    warn "${DOMAIN} resolves to ${RESOLVED}, but this server is ${PUBLIC_IP}."
    warn "If that is a proxy in front of the server, carry on. If it is an old"
    warn "A record, fix it first — the certificate request will fail."
  else
    ok "${DOMAIN} points at this server"
  fi

  if ! command -v nginx >/dev/null 2>&1 || ! command -v certbot >/dev/null 2>&1; then
    echo "    Installing nginx and certbot…"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq nginx certbot python3-certbot-nginx >/dev/null \
      || die "Could not install nginx and certbot."
  fi
  ok "nginx and certbot present"

  VHOST="/etc/nginx/sites-available/reconcilia-${DOMAIN}"
  if [[ -f "$VHOST" ]] && grep -q "managed by Certbot" "$VHOST"; then
    ok "nginx already configured for ${DOMAIN} with a certificate — left as it is"
  else
    cat > "$VHOST" <<NGINX
# Reconcilia — written by server-setup.sh. Certbot adds the TLS server block
# below this one; re-running the installer will not overwrite its work.
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    # Bank statements are several megabytes. nginx defaults to 1 MB, which
    # turns an upload into a bare 413 with nothing in the application's log.
    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:${WANT_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # Uploading a statement returns as soon as the job is queued, but OCR
        # of a long statement can hold the connection while it is read.
        proxy_read_timeout 120s;
    }
}
NGINX
    ln -sf "$VHOST" "/etc/nginx/sites-enabled/reconcilia-${DOMAIN}"
    ok "Wrote $VHOST"
  fi

  nginx -t >/dev/null 2>&1 || { nginx -t; die "The nginx configuration is not valid. The error is above."; }
  systemctl enable --now nginx >/dev/null 2>&1 || true
  systemctl reload nginx >/dev/null 2>&1 || systemctl restart nginx
  systemctl is-active --quiet nginx || die "nginx would not start. Check: journalctl -u nginx -n 40"
  ok "nginx is running"

  # Prove the vhost actually reaches the application before asking for a
  # certificate for it.
  if curl -fsS --max-time 10 -H "Host: ${DOMAIN}" http://127.0.0.1/api/health 2>/dev/null | grep -q '"status":"ok"'; then
    ok "nginx reaches the application"
  else
    die "nginx is up but does not reach the application on 127.0.0.1:${WANT_PORT}. Check: docker compose ps"
  fi

  # Let's Encrypt rejects addresses at names it cannot deliver to, and the
  # default administrator address is deliberately a local one.
  CERT_EMAIL="${LE_EMAIL:-$ADMIN_EMAIL}"
  if [[ "$CERT_EMAIL" =~ \.(local|internal|localdomain|lan|test|invalid|example)$ ]]; then
    warn "No routable contact address, so the certificate is registered without one."
    warn "You will not be emailed if renewal ever stops working."
    EMAIL_ARG=(--register-unsafely-without-email)
  else
    EMAIL_ARG=(--email "$CERT_EMAIL")
  fi

  step "Requesting the certificate"
  if [[ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
    ok "A certificate for ${DOMAIN} is already installed — renewal is automatic"
  elif certbot --nginx -d "$DOMAIN" \
       --non-interactive --agree-tos --redirect --keep-until-expiring \
       "${EMAIL_ARG[@]}"; then
    ok "Certificate installed, and HTTP now redirects to HTTPS"
  else
    die "Certbot failed. The reason is above. The application is still running on http://${DOMAIN} — fix the cause and re-run this same command."
  fi

  # Renewal is a systemd timer that certbot's package installs; make sure it is
  # actually enabled, because a certificate that silently expires in 90 days is
  # worse than not having one.
  systemctl enable --now certbot.timer >/dev/null 2>&1 || true

  step "Checking the site over HTTPS"
  HTTPS_OK=false
  for _ in $(seq 1 10); do
    if curl -fsS --max-time 10 "https://${DOMAIN}/api/health" 2>/dev/null | grep -q '"status":"ok"'; then
      HTTPS_OK=true; break
    fi
    sleep 3
  done
  if [[ "$HTTPS_OK" == true ]]; then
    ok "https://${DOMAIN} is answering"
    # Only now is it safe. Setting this while the site is still plain HTTP
    # makes the browser drop the session cookie, and the sign-in page loops
    # back to itself looking broken when nothing is wrong.
    if [[ "$(env_get COOKIE_SECURE)" != "true" ]]; then
      env_set COOKIE_SECURE true
      docker compose up -d >/dev/null
      ok "Session cookies are now HTTPS-only"
    fi
  else
    warn "https://${DOMAIN} did not answer. The certificate may still be fine —"
    warn "check from your own machine. COOKIE_SECURE has been left off until it does."
  fi
fi

# --- 9. credentials --------------------------------------------------------
CRED_FILE="$PROJECT_DIR/FIRST-LOGIN.txt"
cat > "$CRED_FILE" <<EOF
Reconcilia — first sign-in
==========================
Address   ${SITE_URL}
Email     ${ADMIN_EMAIL}
Password  ${ADMIN_PASSWORD:-see the output of: docker compose exec api python -m app.seed}

Change this password after signing in: click your name, then Change password.
Delete this file once you have.

Everything else lives in ${PROJECT_DIR}/.env — keep it secret and back it up.
Losing SECRET_KEY only signs everyone out; losing POSTGRES_PASSWORD while the
volume survives is recoverable, but losing the volume loses the records.
EOF
chmod 600 "$CRED_FILE"

step "Status"
docker compose ps

cat <<EOF

${GREEN}${BOLD}Reconcilia is running.${OFF}

  Open      ${BOLD}${SITE_URL}${OFF}
  Email     ${BOLD}${ADMIN_EMAIL}${OFF}
  Password  ${BOLD}${ADMIN_PASSWORD:-see the seed output above}${OFF}

  Also written to ${CRED_FILE} (readable by root only).

${BOLD}Next${OFF}
  1. Sign in and change that password.
  2. Settings → Shops, and Settings → Banks: put in the real names and account
     numbers. The shops are seeded as "Shop 1/2/3" placeholders.
  3. Bank statements → Upload: try one real PDF and check what it extracted.

${BOLD}Day to day, from ${PROJECT_DIR}${OFF}
  docker compose logs -f api worker     watch what is happening
  docker compose ps                     what is running
  docker compose restart api            restart just the API
  ./backup.sh                           dump the database and the stored PDFs
  sudo ./server-setup.sh --update       rebuild after changing the code
  docker compose down                   stop (data is kept)

EOF

if [[ "$FRONTED" == true ]]; then
  COOKIE_SECURE_NOW="$(env_get COOKIE_SECURE)"
  if [[ "$SITE_URL" == https://* && "$COOKIE_SECURE_NOW" != "true" ]]; then
    cat <<EOF

${YELLOW}${BOLD}One setting left${OFF}
  ${SITE_URL} is HTTPS but COOKIE_SECURE is still false, so session cookies
  may still be sent over a plain connection. Once you have loaded that address
  in a browser and it works:

    sed -i 's|^COOKIE_SECURE=.*|COOKIE_SECURE=true|' .env && docker compose up -d
EOF
  fi
else
  cat <<EOF

${YELLOW}${BOLD}Before this holds real money${OFF}
  This is plain HTTP. Passwords and session cookies cross the network in clear
  text. Put a domain and a certificate in front of it, then set
  COOKIE_SECURE=true in .env and run: docker compose up -d
EOF
fi
