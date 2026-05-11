# Production Runbook

This deployment is a Docker Compose polling bot plus PostgreSQL. There is no
HTTP health endpoint in the current runtime; liveness is checked with a local
heartbeat file written by the polling process.

## Build And Start

1. Copy `.env.example` to `.env` and fill real values. Do not commit `.env`.
2. Keep `TZ=UTC` unless there is a deliberate server-wide reason to change it.
3. Validate and start:

```bash
docker compose config
docker compose up -d --build
docker compose ps
```

The image installs `requirements.lock`, installs the app with `--no-deps`, and
runs as the non-root `app` user. The Docker context is allow-listed by
`.dockerignore`, so `.env`, local state, tmp files, dumps, and backups are not
sent to the build context.

## Smoke And Liveness

The regular container healthcheck is local-only:

```bash
python -m diet_bot.healthcheck --strict --polling-liveness
```

It checks package data, production config, PostgreSQL, payment guardrail buttons,
and the polling heartbeat file. It does not call Telegram. For cron or systemd
alerts on the VPS:

```bash
scripts/ops/smoke_liveness.sh
```

The script exits non-zero on failure, which is suitable for alert hooks.

Run the Telegram API smoke manually after deploys or token/support-chat changes:

```bash
docker compose --profile smoke run --rm bot-smoke
```

## Backups

Create a custom-format PostgreSQL dump:

```bash
BACKUP_DIR=/srv/diet-bot/backups RETENTION_DAYS=14 scripts/ops/backup_postgres.sh
```

If `DATABASE_URL` is set, the script uses host `pg_dump`. Otherwise it runs
`pg_dump` inside the Compose `postgres` service. Passwords come from the
environment or Compose service env, never from the script. Files are created
with a private umask and old `diet_bot_*.dump` files are deleted after retention.

## Restore Drill

Restore only into a disposable test database:

```bash
BACKUP_FILE=/srv/diet-bot/backups/diet_bot_YYYYMMDDTHHMMSSZ.dump \
TEST_DATABASE_URL=postgresql://user:password@localhost:5432/diet_bot_test \
RESTORE_CONFIRM_TEST_DB=1 \
scripts/ops/restore_postgres_drill.sh
```

The script refuses to run unless the target looks like test, staging, or local,
or `RESTORE_ALLOW_NON_TEST_URL=1` is set after manual verification. It also
refuses when `TEST_DATABASE_URL` equals `DATABASE_URL`.

An optional app smoke can run after restore:

```bash
RESTORE_SMOKE_COMMAND='python -m diet_bot.healthcheck' scripts/ops/restore_postgres_drill.sh
```

## Shutdown

Compose uses `init: true` for the bot and `stop_grace_period: 45s`. During
shutdown the app marks the polling heartbeat as stopping, cancels background
tasks, closes the Telegram bot session, and removes the heartbeat file.

## Container Content Check

After a build, verify secrets and local state are absent:

```bash
docker run --rm --entrypoint sh telegram-diet-bot-bot -c \
  'test ! -e /app/.env && test ! -d /app/.diet_bot_state && test ! -d /app/tmp'
```

If the Compose image name differs, get it with:

```bash
docker compose images
```
