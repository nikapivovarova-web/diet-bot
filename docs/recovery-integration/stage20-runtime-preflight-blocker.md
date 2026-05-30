# Stage 20D Runtime Preflight Worker-Flags Blocker

## Scope

Fixed only the runtime/preflight blocker reported for:

`tests/test_postgres_runtime_preflight.py::test_startup_preflight_validators_pass_against_fully_migrated_postgres`

## Root Cause

The Postgres runtime-preflight integration fixture creates a valid
`production` + `postgres` runtime config and expects all startup validators to
pass. After the Stage 19.1 B-1 worker guard, production Postgres configs are no
longer valid unless both durable worker flags are enabled:

- `DIET_BOT_ONE_DAY_WORKER_ENABLED=1`
- `DIET_BOT_WEEKLY_PDF_WORKER_ENABLED=1`

The fixture was stale; this was not a production preflight bug.

## Change

Updated the valid Postgres runtime-preflight fixture to include both worker
flags. Missing-worker guard assertions remain covered by the runtime config,
healthcheck, and production preflight tests.

## Verification

Commands run:

- `pytest tests/test_postgres_runtime_preflight.py::test_startup_preflight_validators_pass_against_fully_migrated_postgres -q`
  - local result: `1 skipped` because `DIET_BOT_TEST_DATABASE_URL` is not set.
- `pytest tests/test_postgres_runtime_preflight.py::test_startup_preflight_validators_pass_against_fully_migrated_postgres -q -rs`
  - skip reason confirmed: `set DIET_BOT_TEST_DATABASE_URL to run Postgres runtime preflight integration tests`.
- `pytest tests/test_postgres_runtime_preflight.py -q`
  - `4 skipped` because `DIET_BOT_TEST_DATABASE_URL` is not set locally.
- `pytest tests/test_healthcheck.py tests/test_runtime_config.py tests/test_production_preflight.py -q`
  - `73 passed`.
- `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF working-copy warnings.

## Guardrail Confirmation

- B-1 production worker guard was not weakened.
- No payment/store tests were changed.
- No PDF, recipe, Telegram UI, promo behavior, or weekly PDF accepted-text test
  work was done.
- Bot was not launched.
- No deploy, push, commit, tag, PR, secrets/env-file, archive,
  `New project 2 CLEAN`, or recovered-bot work was done.
