# Production Deploy Runbook

Date: 2026-05-17

Scope: production deployment plan and runbook for the FoodBalance Telegram bot.
This document does not perform a deploy, create infrastructure, buy services,
push code, or change application runtime code. Keep real secrets only in the
deployment host secret store or host-local env files with `0600` permissions.

## Launch Target

- VPS: Hetzner CPX41/CPX42 class, 16 GB RAM.
- Runtime: Docker Compose on one VPS.
- Services: bot container, PostgreSQL, Metabase OSS, Caddy or Nginx HTTPS
  reverse proxy, backup job.
- Telegram transport: polling only; no public webhook is required.
- Payments: Telegram Stars monthly auto-renewing subscription and YooKassa
  monthly one-time 30-day access.
- Analytics: Metabase reads `analytics_events` and `user_attribution` through a
  read-only PostgreSQL user.
- Public access: only HTTPS for Metabase and optional public pages; PostgreSQL
  must not be exposed to the public internet.

## Paid Services And Monthly Estimate

Pricing changes. Re-check the linked source pages before buying services.
The estimates below are exclusive of VAT and ignore traffic/storage overages.

Recommended default: Hetzner EU region, e.g. Nuremberg or Falkenstein, because
Hetzner Object Storage is available in the EU locations and internal traffic in
the `eu-central` network zone is free according to Hetzner docs.

| Item | Recommendation | Estimate |
| --- | --- | ---: |
| VPS | Hetzner CPX42 class in EU, 16 GB RAM class | EUR 25.49/mo |
| Primary IPv4 | One Cloud Primary IPv4 | EUR 0.50/mo |
| Hetzner Backups | Enable Backups on the VPS; 7 backup slots | 20% of VPS price, about EUR 5.10/mo |
| Object Storage | Hetzner Object Storage base account for daily `pg_dump` backups | EUR 6.49/mo |
| Domain | Cloudflare Registrar or another low-markup registrar | about USD 10-20/year, roughly USD 1-2/mo |
| Expected total | EU CPX42, IPv4, backups, object storage, one domain | about EUR 37-39/mo plus domain, VAT, and overages |

US alternative if latency or account policy requires it: Hetzner CPX41 class in
the USA is materially more expensive. The current official price-adjustment
table lists CPX41 USA at USD 46.49/mo. With Primary IPv4, Backups at 20%, Object
Storage base, and a domain, budget about USD 65-67/mo before tax and overages.

Sources checked on 2026-05-17:

- Hetzner cloud price adjustment: https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/
- Hetzner Primary IP pricing: https://docs.hetzner.com/cloud/servers/primary-ips/overview/
- Hetzner Backups billing: https://docs.hetzner.com/cloud/billing/faq/
- Hetzner Object Storage overview: https://docs.hetzner.com/storage/object-storage/overview/
- Hetzner Object Storage product page: https://www.hetzner.com/storage/object-storage/
- Cloudflare Registrar docs: https://developers.cloudflare.com/registrar/

## Server Provisioning

Use a fresh Ubuntu LTS server. Conservative recommendation for first production:
Ubuntu Server 24.04 LTS unless Hetzner's image catalog and Docker package
support are already clean for Ubuntu Server 26.04 LTS. Ubuntu 26.04 LTS was
released in April 2026 and is a valid later upgrade target after the first
point-release window and staging proof.

Base provisioning checklist:

- Create the VPS with one Primary IPv4 and the default IPv6.
- Add only SSH public keys during provisioning. Disable password login.
- Create a non-root admin user with sudo access.
- Enable Hetzner Cloud Firewall or `ufw`.
- Allow only:
  - `22/tcp` for SSH, ideally restricted to admin IPs.
  - `80/tcp` and `443/tcp` for Caddy/Nginx HTTP-to-HTTPS and HTTPS.
- Do not publish PostgreSQL (`5432`) or Metabase (`3000`) directly.
- Apply OS security updates before installing Docker.

Initial host hardening commands:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y ufw fail2ban unattended-upgrades ca-certificates curl git jq
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

SSH hardening:

```bash
sudo install -m 0755 -d /etc/ssh/sshd_config.d
printf '%s\n' \
  'PasswordAuthentication no' \
  'PermitRootLogin no' \
  'PubkeyAuthentication yes' \
  | sudo tee /etc/ssh/sshd_config.d/99-foodbalance-hardening.conf
sudo sshd -t
sudo systemctl reload ssh
```

Install Docker Engine and Compose plugin from Docker's official apt repository.
Reference: https://docs.docker.com/engine/install/ubuntu/

```bash
sudo apt remove -y docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc || true
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
```

## Directory Layout

Use `/srv/foodbalance` as the deployment root. Keep runtime secrets outside the
repo checkout.

```text
/srv/foodbalance/
  app/                         # Git checkout or copied release artifact
  env/
    bot.env                    # bot env, chmod 0600, never committed
    postgres.env               # PostgreSQL passwords/users, chmod 0600
    metabase.env               # Metabase app DB secrets, chmod 0600
    backup.env                 # S3/Object Storage credentials, chmod 0600
  postgres/
    data/                      # PostgreSQL bind mount, or use a named volume
  metabase/
    data/                      # only if using local Metabase app storage
  proxy/
    Caddyfile                  # or nginx conf, may be generated from templates
  backups/
    pgdump/                    # short local retention only
    restore-drills/            # disposable restore evidence
  logs/
    backup/                    # backup job logs, no secrets
    smoke/                     # redacted smoke evidence
```

Permissions baseline:

```bash
sudo mkdir -p /srv/foodbalance/{app,env,postgres/data,metabase/data,proxy,backups/pgdump,backups/restore-drills,logs/backup,logs/smoke}
sudo chown -R root:docker /srv/foodbalance
sudo chmod 0750 /srv/foodbalance /srv/foodbalance/env
sudo find /srv/foodbalance/env -type f -name '*.env' -exec chmod 0600 {} +
```

## Docker Compose Architecture

This docs slice does not add `Dockerfile` or `docker-compose.yml`. The production
Compose stack should have this shape when deploy artifacts are present:

| Service | Role | Network exposure | Persistence |
| --- | --- | --- | --- |
| `bot` | Runs `python -m diet_bot.telegram_app` or installed script; Telegram polling | No public ports | Logs only; state in PostgreSQL |
| `postgres` | Production database | Internal Compose network only | `/srv/foodbalance/postgres/data` or named volume |
| `metabase` | Metabase OSS UI | Internal only, proxied by Caddy/Nginx over HTTPS | Separate Metabase app DB or Metabase data volume |
| `caddy` or `nginx` | HTTPS reverse proxy | `80/tcp`, `443/tcp` | Config and cert storage |
| `backup` | Daily `pg_dump -Fc` to Object Storage | No public ports | `/srv/foodbalance/backups/pgdump` short retention |

Compose rules:

- Do not publish PostgreSQL to the host public interface.
- Put `bot`, `postgres`, `metabase`, and proxy on a private Compose network.
- Expose Metabase only through HTTPS and Metabase auth.
- Prefer Caddy for automatic HTTPS unless Nginx is already standard in the ops
  environment.
- Use Docker restart policies, e.g. `restart: unless-stopped`, for `bot`,
  `postgres`, `metabase`, and proxy.
- Configure Docker log rotation for all services, e.g. `json-file` with
  `max-size` and `max-file`, or use journald with host retention.

## Secrets And Env Inventory

Never commit real values. Put production values in `/srv/foodbalance/env/*.env`,
the host secret manager, or the deployment platform secret store. Do not paste
tokens, DB URLs with passwords, S3 keys, payment charge ids, email addresses, or
raw payment payloads into docs, logs, screenshots, tickets, or chat.

Required bot env:

```dotenv
DIET_BOT_ENV=production
DIET_BOT_PUBLIC_PAYMENTS_ENABLED=1
DIET_BOT_PAYMENT_TEST_PRICES_ENABLED=0
DIET_BOT_TESTER_CHAT_IDS=
DIET_BOT_DATABASE_URL=REPLACE_WITH_PRODUCTION_POSTGRES_URL
DIET_BOT_DB_POOL_MAX_SIZE=20
DIET_BOT_ADMIN_USER_IDS=498196878
DIET_BOT_TOKEN=REPLACE_WITH_RELEASE_TELEGRAM_BOT_TOKEN
TELEGRAM_PROVIDER_TOKEN=REPLACE_WITH_LIVE_YOOKASSA_TELEGRAM_PROVIDER_TOKEN
```

Recommended optional bot env:

```dotenv
DIET_BOT_SUPPORT_CHAT_ID=REPLACE_WITH_SUPPORT_CHAT_ID
DIET_BOT_POSTGRES_STATEMENT_TIMEOUT_MS=5000
DIET_BOT_POSTGRES_LOCK_TIMEOUT_MS=1000
PYTHONPATH=src
```

PostgreSQL env:

```dotenv
POSTGRES_DB=diet_bot_prod
POSTGRES_USER=postgres
POSTGRES_PASSWORD=REPLACE_WITH_RANDOM_ADMIN_PASSWORD
DIET_BOT_DB_PASSWORD=REPLACE_WITH_RANDOM_APP_PASSWORD
METABASE_RO_PASSWORD=REPLACE_WITH_RANDOM_ANALYTICS_READONLY_PASSWORD
METABASE_APP_DB_PASSWORD=REPLACE_WITH_RANDOM_METABASE_APP_DB_PASSWORD
```

Metabase env:

```dotenv
MB_DB_TYPE=postgres
MB_DB_HOST=postgres
MB_DB_PORT=5432
MB_DB_DBNAME=metabase_app
MB_DB_USER=metabase_app
MB_DB_PASS=REPLACE_WITH_RANDOM_METABASE_APP_DB_PASSWORD
MB_SITE_URL=https://metabase.example.com
```

Object Storage backup env:

```dotenv
S3_ENDPOINT=https://REPLACE_WITH_HETZNER_OBJECT_STORAGE_ENDPOINT
S3_REGION=REPLACE_WITH_REGION
S3_BUCKET=foodbalance-prod-pgdump
S3_ACCESS_KEY_ID=REPLACE_WITH_ACCESS_KEY
S3_SECRET_ACCESS_KEY=REPLACE_WITH_SECRET_KEY
BACKUP_RETENTION_DAYS_LOCAL=14
BACKUP_RETENTION_DAYS_OBJECT=35
```

## Database Setup

Use one production database for the bot and a separate database for Metabase's
own application state. Metabase analytics access to the bot DB must be read-only
and limited to analytics tables.

Databases and roles:

- `diet_bot_prod`: production app DB.
- `diet_bot_app`: app role, owns and migrates production app schema.
- `diet_bot_analytics_ro`: read-only role for Metabase questions/dashboards.
- `metabase_app`: separate DB and role for Metabase's own metadata.

Initial SQL shape. Run as PostgreSQL admin. Use `\prompt -s` or a host secret
tool so passwords are not written to shell history or files.

```sql
\prompt -s 'diet_bot_app password: ' diet_bot_app_password
\prompt -s 'diet_bot_analytics_ro password: ' diet_bot_analytics_ro_password
\prompt -s 'metabase_app password: ' metabase_app_password

CREATE ROLE diet_bot_app LOGIN PASSWORD :'diet_bot_app_password';
CREATE DATABASE diet_bot_prod OWNER diet_bot_app;

CREATE ROLE metabase_app LOGIN PASSWORD :'metabase_app_password';
CREATE DATABASE metabase_app OWNER metabase_app;

CREATE ROLE diet_bot_analytics_ro LOGIN PASSWORD :'diet_bot_analytics_ro_password';
GRANT CONNECT ON DATABASE diet_bot_prod TO diet_bot_analytics_ro;
\connect diet_bot_prod
GRANT USAGE ON SCHEMA public TO diet_bot_analytics_ro;
```

After the bot migrations have created tables, grant analytics access:

```sql
\connect diet_bot_prod
GRANT SELECT ON TABLE analytics_events, user_attribution TO diet_bot_analytics_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE diet_bot_app IN SCHEMA public
  GRANT SELECT ON TABLES TO diet_bot_analytics_ro;
```

Migration rule:

- `PostgresDietBotStore.initialize()` runs idempotent app migrations.
- Do not let Metabase connect as `diet_bot_app` or a PostgreSQL admin role.
- Do not grant Metabase read access to payment, entitlement, support, or profile
  tables unless a separate privacy review approves it.

One-off migration command before starting polling:

```bash
docker compose run --rm bot python - <<'PY'
from diet_bot.postgres_store import PostgresDietBotStore
from diet_bot.runtime_config import load_runtime_config

config = load_runtime_config()
store = PostgresDietBotStore(
    config.database_url,
    statement_timeout_ms=config.postgres_statement_timeout_ms,
    lock_timeout_ms=config.postgres_lock_timeout_ms,
    pool_max_size=config.postgres_pool_max_size,
)
try:
    store.initialize()
finally:
    store.close()
print("postgres migrations: ok")
PY
```

## Backups

Use two independent backup layers:

- Hetzner Backups on the VPS for whole-server disaster recovery. Hetzner bills
  Backups at 20% of the server price and provides 7 backup slots.
- Daily PostgreSQL custom-format dumps uploaded to Object Storage.

Daily backup command shape:

```bash
set -euo pipefail
backup_dir=/srv/foodbalance/backups/pgdump
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_file="$backup_dir/diet_bot_prod_$stamp.dump"

docker compose exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_file"
test -s "$backup_file"
aws --endpoint-url "$S3_ENDPOINT" s3 cp "$backup_file" "s3://$S3_BUCKET/postgres/daily/$(basename "$backup_file")"
find "$backup_dir" -type f -name 'diet_bot_prod_*.dump' -mtime +"${BACKUP_RETENTION_DAYS_LOCAL:-14}" -delete
```

Retention:

- Local host: 14 days.
- Object Storage daily: 35 days.
- Object Storage monthly: 12 months if the business needs month-end rollback
  points.
- Keep restore-drill evidence, not secret dumps, in `/srv/foodbalance/logs/smoke`.

Restore drill:

- Run at least once before launch.
- Repeat monthly or before risky storage/payment releases.
- Restore only into a disposable DB first.

Disposable restore drill shape:

```bash
latest_dump=/srv/foodbalance/backups/pgdump/REPLACE_WITH_LATEST.dump
docker compose exec -T postgres sh -lc 'createdb -U "$POSTGRES_USER" diet_bot_restore_drill'
cat "$latest_dump" | docker compose exec -T postgres sh -lc \
  'pg_restore -U "$POSTGRES_USER" --dbname diet_bot_restore_drill --clean --if-exists'
docker compose exec -T postgres sh -lc \
  'psql -U "$POSTGRES_USER" --dbname diet_bot_restore_drill --command "select count(*) as analytics_events from analytics_events;"'
docker compose exec -T postgres sh -lc 'dropdb -U "$POSTGRES_USER" diet_bot_restore_drill'
```

Production restore rule:

- Stop the bot before restoring production.
- Take a fresh pre-restore backup first.
- Restore to disposable DB first and inspect table counts.
- Restore production only with explicit owner approval.
- After restoring, reconcile any payments/subscriptions that happened after the
  restored backup timestamp. A DB restore can lose newer paid entitlements.

## Monitoring And Health

Healthcheck commands:

```bash
docker compose run --rm bot python -m diet_bot.healthcheck --package-data-only
docker compose run --rm bot python -m diet_bot.healthcheck --strict
```

Expected output:

```text
healthcheck: ok
```

Operational checks:

```bash
docker compose ps
docker compose logs --since=30m bot
docker compose logs --since=30m postgres
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "select count(*) as connections from pg_stat_activity where datname = current_database();"
df -h
docker system df
du -sh /srv/foodbalance/postgres/data /srv/foodbalance/backups/pgdump
```

Alert manually or through the chosen monitor when:

- `bot` is restarting repeatedly or stopped.
- Strict healthcheck fails.
- PostgreSQL connection count approaches `DIET_BOT_DB_POOL_MAX_SIZE` or the DB
  max connection limit.
- Disk usage exceeds 75%; stop and investigate before 90%.
- Daily backup is missing, empty, or not uploaded to Object Storage.
- Metabase cannot query `analytics_events` or `user_attribution`.
- Logs contain token-looking strings, DB URLs, S3 keys, raw provider payloads, or
  unredacted payment/customer data.

Log rotation:

- Configure Docker log rotation in Compose or daemon config.
- Rotate `/srv/foodbalance/logs/backup/*.log`.
- Keep payment smoke screenshots and DB evidence redacted.

## Deploy Steps

These are launch-day steps to run on the production host after infrastructure is
created. They were not run as part of this docs slice.

1. Point DNS.
   - Create `A` and optional `AAAA` records for Metabase/proxy hostnames.
   - Wait for DNS propagation before requesting HTTPS certificates.

2. Prepare release artifact.
   - Clone or copy the reviewed repo into `/srv/foodbalance/app`.
   - Confirm exact commit SHA.
   - Do not copy `.env`, `.diet_bot_state`, local logs, dumps, or smoke files.

3. Install host env files.
   - Create `/srv/foodbalance/env/*.env` with production values.
   - `chmod 0600 /srv/foodbalance/env/*.env`.
   - Confirm no real secrets exist inside the repo checkout.

4. Validate Compose.

```bash
cd /srv/foodbalance/app
docker compose config
```

5. Build image.

```bash
docker compose build bot
docker compose run --rm bot python -m diet_bot.healthcheck --package-data-only
```

6. Start PostgreSQL and proxy dependencies.

```bash
docker compose up -d postgres
docker compose ps postgres
```

7. Run migrations and strict healthcheck.

```bash
docker compose run --rm bot python - <<'PY'
from diet_bot.postgres_store import PostgresDietBotStore
from diet_bot.runtime_config import load_runtime_config

config = load_runtime_config()
store = PostgresDietBotStore(
    config.database_url,
    statement_timeout_ms=config.postgres_statement_timeout_ms,
    lock_timeout_ms=config.postgres_lock_timeout_ms,
    pool_max_size=config.postgres_pool_max_size,
)
try:
    store.initialize()
finally:
    store.close()
print("postgres migrations: ok")
PY
docker compose run --rm bot python -m diet_bot.healthcheck --strict
```

8. Start Metabase and HTTPS proxy.

```bash
docker compose up -d metabase caddy
docker compose ps metabase caddy
```

9. Configure Metabase.
   - Create the first Metabase admin over HTTPS.
   - Connect to `diet_bot_prod` with `diet_bot_analytics_ro`.
   - Confirm only `analytics_events` and `user_attribution` are visible.

10. Start the bot.

```bash
docker compose up -d bot
docker compose ps bot
docker compose logs --since=5m bot
```

11. Verify Telegram polling.
   - Confirm no webhook is configured unless intentionally migrated away from
     polling.
   - If an old webhook exists, delete it before relying on polling.

```bash
curl -sS "https://api.telegram.org/bot${DIET_BOT_TOKEN}/getWebhookInfo" | jq .
# Only if the response shows an old webhook URL:
curl -sS -X POST "https://api.telegram.org/bot${DIET_BOT_TOKEN}/deleteWebhook?drop_pending_updates=false" | jq .
```

12. Record launch evidence.
   - Commit SHA, image id, host, timestamp, healthcheck output, backup result,
     and redacted smoke notes.

## Production Smoke

Do this before opening ads or paid traffic.

Environment confirmation:

- `DIET_BOT_ENV=production`.
- `DIET_BOT_PUBLIC_PAYMENTS_ENABLED=1`.
- `DIET_BOT_PAYMENT_TEST_PRICES_ENABLED=0`.
- `DIET_BOT_TESTER_CHAT_IDS=` is empty.
- `DIET_BOT_DATABASE_URL` points to production PostgreSQL.
- `DIET_BOT_DB_POOL_MAX_SIZE=20`.
- `DIET_BOT_ADMIN_USER_IDS=498196878`.
- `TELEGRAM_PROVIDER_TOKEN` is the live YooKassa Telegram provider token.
- No token, DB password, S3 secret, customer email, or raw payment payload is
  present in logs or evidence.

Bot smoke:

- Send `/start`; confirm welcome flow and attribution deep links still work.
- Send `/plan`; complete a normal profile and generate a one-day plan.
- Confirm profile reuse/edit path works.
- Confirm no local JSON files are receiving production paid state.
- Confirm weekly PDF delivery if the release gate requires it.

Payment no-payment invoice screen checks:

- As a non-tester user, open the subscription/paywall path.
- Confirm production prices only:
  - Stars monthly subscription: `450` Stars, auto-renewing monthly.
  - YooKassa monthly access: `799 RUB`, one-time 30-day access.
  - One-day extra: `69 RUB` or `40` Stars.
  - Weekly PDF extra: `349 RUB` or `199` Stars.
- Confirm no `[TEST]` label or smoke price is visible.
- Open the Stars invoice screen and back out before paying.
- Open the YooKassa invoice screen and back out before paying.
- Do not complete a real payment unless the owner explicitly approves a real
  payment smoke for that session.

Metabase smoke:

- Log into Metabase over HTTPS.
- Confirm Metabase auth is enabled.
- Confirm dashboards/questions can query `analytics_events`.
- Confirm attribution questions can query `user_attribution`.
- Confirm Metabase cannot read payment, entitlement, profile, support, or raw
  app state tables with the analytics read-only user.

Backup smoke:

- Run one `pg_dump -Fc`.
- Upload it to Object Storage.
- Restore it to a disposable DB.
- Record redacted table-count evidence.

## Rollback

Rollback priority: stop bad behavior first, preserve evidence second, restore
service third.

Stop bot safely:

```bash
docker compose stop bot
docker compose ps bot
```

Pause public sales without stopping the whole stack:

```bash
# Edit only the host-local env file, not the repo:
# DIET_BOT_PUBLIC_PAYMENTS_ENABLED=0
docker compose up -d bot
```

Rollback to previous image or commit:

```bash
docker compose stop bot
git rev-parse HEAD
git log --oneline -5
# Select the known-good commit or image tag from release notes.
git switch --detach REPLACE_WITH_PREVIOUS_GOOD_COMMIT
docker compose build bot
docker compose run --rm bot python -m diet_bot.healthcheck --strict
docker compose up -d bot
docker compose logs --since=10m bot
```

Database rollback rules:

- Prefer code rollback when schema is backward-compatible.
- Do not run destructive DB changes during emergency rollback unless a written
  incident lead approves it.
- Never restore over production while the bot is running.
- Always take a fresh pre-restore backup.
- Restore to disposable DB first.
- If restoring production, document the cutoff timestamp and reconcile payments,
  entitlements, and support actions after that timestamp.

Production DB restore shape:

```bash
docker compose stop bot
pre_restore=/srv/foodbalance/backups/pgdump/pre_restore_$(date -u +%Y%m%dT%H%M%SZ).dump
docker compose exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$pre_restore"
test -s "$pre_restore"
cat REPLACE_WITH_APPROVED_DUMP.dump | docker compose exec -T postgres sh -lc \
  'pg_restore -U "$POSTGRES_USER" --dbname "$POSTGRES_DB" --clean --if-exists --single-transaction'
docker compose run --rm bot python -m diet_bot.healthcheck --strict
docker compose up -d bot
```

## Launch Checklist

Do not start ads, influencer traffic, or public paid promotion until every item
below is complete.

- VPS provisioned with SSH key-only access.
- Firewall allows only SSH, HTTP, and HTTPS.
- Docker and Compose installed from official Docker repository.
- Repo or release artifact deployed without `.env`, local state, logs, dumps, or
  secrets.
- Production env files installed with `0600` permissions.
- PostgreSQL initialized and app migrations applied.
- Metabase app DB is separate from app production DB.
- Metabase analytics connection uses `diet_bot_analytics_ro`.
- Caddy/Nginx HTTPS works; Metabase is not exposed over plain HTTP.
- Bot strict healthcheck prints `healthcheck: ok`.
- Bot container is running and polling.
- No old Telegram webhook is active unless intentionally configured.
- Production prices are visible; test prices are not visible.
- `DIET_BOT_TESTER_CHAT_IDS` is empty.
- Stars/YooKassa invoice screens were checked without payment.
- Real payment smoke, if needed, has explicit owner approval for that session.
- Daily `pg_dump` backup succeeded and uploaded to Object Storage.
- Restore drill to disposable DB passed.
- Hetzner Backups are enabled.
- Disk, DB connection, container, and backup monitoring checks are in place.
- Redacted smoke evidence is stored under `/srv/foodbalance/logs/smoke`.
- Incident rollback target is known: previous image tag or commit SHA.
- Owner signs off before opening paid traffic or ads.
