#!/usr/bin/env bash
# Dumps the database and the stored statement PDFs into ./backups.
# Run it on the server, from the project directory. Financial records deserve
# a backup that someone has actually tested restoring.
set -euo pipefail

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="${1:-./backups}"
mkdir -p "$OUT"

echo "==> Dumping the database"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-reconcilia}" \
  "${POSTGRES_DB:-reconcilia}" | gzip > "$OUT/db-$STAMP.sql.gz"

echo "==> Archiving the uploaded statements"
docker compose exec -T api tar -cf - -C /app storage | gzip > "$OUT/statements-$STAMP.tar.gz"

echo "Wrote:"
ls -lh "$OUT/db-$STAMP.sql.gz" "$OUT/statements-$STAMP.tar.gz"
echo
echo "To restore the database into a fresh stack:"
echo "  gunzip -c db-$STAMP.sql.gz | docker compose exec -T db psql -U reconcilia reconcilia"
