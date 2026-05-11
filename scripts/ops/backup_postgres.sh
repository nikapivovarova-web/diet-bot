#!/usr/bin/env sh
set -eu

BACKUP_DIR="${BACKUP_DIR:-./backups/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

case "$RETENTION_DAYS" in
  ''|*[!0-9]*)
    printf '%s\n' "RETENTION_DAYS must be a positive integer." >&2
    exit 2
    ;;
esac
if [ "$RETENTION_DAYS" -lt 1 ]; then
  printf '%s\n' "RETENTION_DAYS must be at least 1." >&2
  exit 2
fi

mkdir -p "$BACKUP_DIR"
BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd)"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="$BACKUP_DIR/diet_bot_${timestamp}.dump"
tmp_file="${backup_file}.tmp"

cleanup() {
  rm -f "$tmp_file"
}
trap cleanup EXIT HUP INT TERM

if [ -n "${DATABASE_URL:-}" ]; then
  pg_dump \
    --format=custom \
    --no-owner \
    --no-privileges \
    --file "$tmp_file" \
    "$DATABASE_URL"
else
  docker compose exec -T postgres sh -c \
    'pg_dump --format=custom --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    > "$tmp_file"
fi

if [ ! -s "$tmp_file" ]; then
  printf '%s\n' "Backup file is empty; refusing to publish it." >&2
  exit 1
fi

mv "$tmp_file" "$backup_file"
find "$BACKUP_DIR" -type f -name 'diet_bot_*.dump' -mtime +"$RETENTION_DAYS" -print -delete
printf 'Backup written: %s\n' "$backup_file"
