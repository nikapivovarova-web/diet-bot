#!/usr/bin/env sh
set -eu

BOT_SERVICE="${BOT_SERVICE:-bot}"
MAX_AGE_SECONDS="${DIET_BOT_POLLING_HEARTBEAT_MAX_AGE_SECONDS:-90}"

case "$MAX_AGE_SECONDS" in
  ''|*[!0-9]*)
    printf '%s\n' "DIET_BOT_POLLING_HEARTBEAT_MAX_AGE_SECONDS must be a positive integer." >&2
    exit 2
    ;;
esac
if [ "$MAX_AGE_SECONDS" -lt 1 ]; then
  printf '%s\n' "DIET_BOT_POLLING_HEARTBEAT_MAX_AGE_SECONDS must be at least 1." >&2
  exit 2
fi

docker compose ps
docker compose exec -T "$BOT_SERVICE" \
  python -m diet_bot.healthcheck \
    --strict \
    --polling-liveness \
    --polling-max-age-seconds "$MAX_AGE_SECONDS"
