#!/usr/bin/env bash
# ===========================================================================
# Reconcilia — one-command installer, run ON the server.
#
#   sudo ./server-setup.sh              install (or update) and start
#   sudo ./server-setup.sh --demo       also load demo shops, sheets and the
#                                       sample statements, then reconcile them
#   sudo ./server-setup.sh --update     rebuild and restart, keeping all data
#
# Safe to run more than once. It never overwrites an existing .env, and it
# never touches the database volume.
# ===========================================================================
set -euo pipefail

WITH_DEMO=false
UPDATE_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --demo)   WITH_DEMO=true ;;
    --update) UPDATE_ONLY=true ;;
    -h|--help)
      sed -n '3,11p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown option: $arg  (try --help)" >&2; exit 1 ;;
  esac
done

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

  ADMIN_MAIL="${ADMIN_EMAIL:-admin@reconcilia.local}"
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

CORS_ORIGINS=http://${PUBLIC_IP}
HTTP_PORT=80

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

# Read the few values this script needs. Sourcing .env as shell would break on
# any value containing a space, and would execute whatever a hand-edited file
# happened to contain.
env_get() {
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" .env \
    | tail -n 1 \
    | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}
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
  ufw allow "${HTTP_PORT}"/tcp >/dev/null 2>&1 || true
  ok "Port ${HTTP_PORT} allowed through ufw"
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

# --- 8. credentials --------------------------------------------------------
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
