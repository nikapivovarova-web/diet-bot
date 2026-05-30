# Stage 19.1 Worker Guard

## Scope

Stage 19.1 B-1 keeps production Postgres startup fail-closed unless both durable
workers are explicitly enabled:

- `DIET_BOT_ONE_DAY_WORKER_ENABLED=1`
- `DIET_BOT_WEEKLY_PDF_WORKER_ENABLED=1`

This stage did not change promo, sales follow-up, PDF rendering, recipes,
payments, deployment scripts, or bot behavior.

## Test Fixture Update

Stale production/Postgres test fixtures that model a valid production runtime now
include both worker flags. Tests that intentionally omit one flag continue to
assert the worker-guard startup issue.

## Verification

The targeted Stage 19.1 verification commands are recorded in
`docs/recovery-integration/recovery-status.md`.
