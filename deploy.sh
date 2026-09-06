#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Copies this project to a server and starts it with Docker Compose.
#
#   ./deploy.sh root@178.128.82.112
#
# Run it from your own computer, not from the server. It needs ssh and rsync
# locally, and Docker with the compose plugin on the server; if Docker is
# missing it offers to install it.
# ---------------------------------------------------------------------------
set -euo pipefail

TARGET="${1:-}"
REMOTE_DIR="${REMOTE_DIR:-/opt/reconcilia}"

if [[ -z "$TARGET" ]]; then
  echo "Usage: ./deploy.sh user@host        (for example: ./deploy.sh root@203.0.113.10)" >&2
  exit 1
fi

here() { cd "$(dirname "${BASH_SOURCE[0]}")" && pwd; }
cd "$(here)"

if [[ ! -f .env ]]; then
  echo "There is no .env file yet."
  echo "  cp .env.example .env    then edit it — SECRET_KEY and both passwords must be changed."
  exit 1
fi

if grep -q "CHANGE_ME" .env; then
  echo "Your .env still contains CHANGE_ME placeholders. Fill them in before deploying:" >&2
  grep -n "CHANGE_ME" .env >&2
  exit 1
fi

echo "==> Checking the server"
ssh "$TARGET" 'command -v docker >/dev/null 2>&1' || {
  read -r -p "Docker is not installed on $TARGET. Install it now? [y/N] " reply
  [[ "$reply" == [yY] ]] || exit 1
  ssh "$TARGET" 'curl -fsSL https://get.docker.com | sh'
}
ssh "$TARGET" 'docker compose version >/dev/null 2>&1' || {
  echo "Docker on $TARGET has no 'compose' plugin. Install docker-compose-plugin and re-run." >&2
  exit 1
}

echo "==> Copying files to $TARGET:$REMOTE_DIR"
ssh "$TARGET" "mkdir -p '$REMOTE_DIR'"
rsync -az --delete \
  --exclude '.git' \
  --exclude 'node_modules' \
  --exclude '.next' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'backend/storage' \
  --exclude 'backend/storage-test' \
  ./ "$TARGET:$REMOTE_DIR/"

echo "==> Building and starting (first run pulls images and compiles; allow a few minutes)"
ssh "$TARGET" "cd '$REMOTE_DIR' && docker compose up -d --build"

echo "==> Waiting for the API to answer"
ssh "$TARGET" "cd '$REMOTE_DIR' && for i in \$(seq 1 60); do
  if docker compose exec -T api curl -fsS http://localhost:8000/api/health >/dev/null 2>&1; then
    echo 'API is up'; exit 0
  fi
  sleep 3
done; echo 'API did not come up in time — check: docker compose logs api'; exit 1"

echo "==> Creating reference data and the first administrator"
ssh "$TARGET" "cd '$REMOTE_DIR' && docker compose exec -T api python -m app.seed"

HOST_ONLY="${TARGET#*@}"
echo
echo "Done. Open  http://$HOST_ONLY  and sign in with the ADMIN_EMAIL in your .env."
echo
echo "Useful afterwards, all run from $REMOTE_DIR on the server:"
echo "  docker compose logs -f api worker     # follow the logs"
echo "  docker compose exec api python -m app.seed --demo   # add demo shops and sheets"
echo "  docker compose down                   # stop (data is kept in named volumes)"
