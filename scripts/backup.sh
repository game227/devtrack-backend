#!/usr/bin/env bash
# Dumps the DevTrack Postgres database to a timestamped, gzip-compressed
# file. Run manually or on a schedule (e.g. a Render cron job or any host
# with `pg_dump` and network access to the database) once DATABASE_URL
# points at the real production database — see docs/BACKUP.md.
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL must be set (postgres://user:pass@host:port/dbname)}"
OUT_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="${OUT_DIR}/devtrack-${TIMESTAMP}.sql.gz"

mkdir -p "$OUT_DIR"
pg_dump "$DATABASE_URL" | gzip > "$OUT_FILE"
echo "Wrote $OUT_FILE"
