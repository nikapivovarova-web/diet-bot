#!/usr/bin/env sh
set -eu

: "${BACKUP_FILE:?set BACKUP_FILE to a .dump created by backup_postgres.sh}"
: "${TEST_DATABASE_URL:?set TEST_DATABASE_URL to a disposable test database URL}"

if [ "${RESTORE_CONFIRM_TEST_DB:-}" != "1" ]; then
  printf '%s\n' "Set RESTORE_CONFIRM_TEST_DB=1 to confirm this is a disposable test DB." >&2
  exit 2
fi

if [ ! -r "$BACKUP_FILE" ]; then
  printf 'Backup file is not readable: %s\n' "$BACKUP_FILE" >&2
  exit 1
fi

if [ -n "${DATABASE_URL:-}" ] && [ "$TEST_DATABASE_URL" = "$DATABASE_URL" ]; then
  printf '%s\n' "TEST_DATABASE_URL matches DATABASE_URL; refusing restore drill." >&2
  exit 2
fi

case "$TEST_DATABASE_URL" in
  *test*|*staging*|*localhost*|*127.0.0.1*)
    ;;
  *)
    if [ "${RESTORE_ALLOW_NON_TEST_URL:-}" != "1" ]; then
      printf '%s\n' "TEST_DATABASE_URL does not look like a test/staging/local DB." >&2
      printf '%s\n' "Set RESTORE_ALLOW_NON_TEST_URL=1 only after verifying the target manually." >&2
      exit 2
    fi
    ;;
esac

pg_restore \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  --dbname "$TEST_DATABASE_URL" \
  "$BACKUP_FILE"

psql "$TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -c 'select 1;' >/dev/null

if [ -n "${RESTORE_SMOKE_COMMAND:-}" ]; then
  DIET_BOT_DATABASE_URL="$TEST_DATABASE_URL" sh -c "$RESTORE_SMOKE_COMMAND"
fi

printf '%s\n' "Restore drill completed successfully."
