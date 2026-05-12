# Production PostgreSQL Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add paid-production durable PostgreSQL storage for FoodBalance while keeping JSON storage dev-only and keeping payment business logic out of the storage PR.

**Architecture:** Introduce a small storage contract first, then add idempotent PostgreSQL migrations and a focused `PostgresDietBotStore` in small tested slices. Wire Telegram runtime to the contract only after the store can persist users, profiles, entitlements, generation records, promo codes, support state, and a payment-orders placeholder table.

**Tech Stack:** Python 3.11, pytest, aiogram 3.x, PostgreSQL, `psycopg[binary]`, PowerShell on Windows.

---

## Hard Boundaries

- Work only in `C:\Users\adck8\Documents\New project 2 CLEAN`.
- Keep `C:\Users\adck8\Documents\New project 2` read-only source material.
- Do not copy old `src/diet_bot/postgres_store.py` wholesale. It is large and old notes flag missing `statement_timeout` and `lock_timeout`.
- Do not copy old `src/diet_bot/telegram_app.py` wholesale. Only storage wiring hunks are allowed when the runtime wiring task starts.
- Do not change payment business rules in this plan. The `payment_orders` table is a storage-level placeholder for future payment-ledger work, not a refund, chargeback, reconciliation, or successful-payment implementation.
- Do not introduce Docker, CI workflows, or payment handler rewrites in the same commit as storage core.
- Do not stage, commit, push, or open a PR unless the user explicitly asks. Commit boundaries below are planned boundaries for future authorized commits.

## Source Findings

- Clean `src/diet_bot/runtime_config.py` currently rejects `DIET_BOT_ENV=production` because durable production storage is not implemented.
- Clean `src/diet_bot/telegram_app.py` stores chat history and profiles in `DIET_BOT_STATE_FILE` JSON and stores entitlements in `DIET_BOT_SUBSCRIPTIONS_STATE_FILE`.
- Clean `src/diet_bot/subscriptions.py` has pure entitlement operations that are useful to keep, but JSON persistence is not transaction safe for paid production.
- Clean `src/diet_bot/promo_codes.py` stores promo records in JSON and activation is not protected by durable row locks.
- Old `postgres_migrations.py` has useful schema and idempotent migration ideas.
- Old `postgres_store.py` has useful transaction, row-lock, generation lifecycle, and migration-lock ideas, but must be adapted into smaller slices with DB statement and lock timeouts.
- Old `json_storage.py` uses a cross-process JSON lock concept, but its file lock blocks without a timeout. JSON fallback must be dev-only and bounded.
- Old `scripts/migrate_json_to_postgres.py` migrates history, subscriptions, payment orders, processed charge registry, and promo codes, but old handoff says `payment_events.json` is not migrated. Paid production migration must therefore wait for payment ledger or run with an explicit non-payment-state limitation.

## Storage Contract For Paid Production

Create `src/diet_bot/storage.py` as the narrow contract used by Telegram runtime. The contract must express durable state transitions without knowing Telegram UI details.

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .promo_codes import PromoCodeActivation, PromoCodeRecord
from .subscriptions import AttemptConsumption, Entitlement, RationKind


@dataclass(frozen=True)
class UserIdentity:
    telegram_id: int
    username: str | None = None
    first_name: str | None = None


@dataclass(frozen=True)
class SupportState:
    user_id: int
    status: str
    last_request_at: datetime | None
    last_admin_message_id: int | None = None


class DietBotStore(Protocol):
    def initialize(self) -> None: ...
    def healthcheck(self) -> None: ...
    def remember_user(self, user: UserIdentity) -> None: ...
    def load_chat_state(self, chat_id: int) -> dict[str, object]: ...
    def save_chat_state(self, chat_id: int, state: dict[str, object]) -> None: ...
    def load_profile_data(self, user_id: int) -> dict[str, object] | None: ...
    def save_profile_data(self, user_id: int, profile_data: dict[str, object]) -> None: ...
    def get_entitlement(self, user_id: int) -> Entitlement: ...
    def save_entitlement(self, user_id: int, entitlement: Entitlement) -> None: ...
    def consume_generation_attempt(self, user_id: int, ration_kind: RationKind) -> AttemptConsumption: ...
    def heartbeat_generation_attempt(self, user_id: int, consumption: AttemptConsumption) -> bool: ...
    def start_generation_delivery(self, user_id: int, consumption: AttemptConsumption) -> bool: ...
    def complete_generation_attempt(
        self,
        user_id: int,
        consumption: AttemptConsumption,
        *,
        pdf_path: str | None = None,
        telegram_message_id: int | None = None,
    ) -> None: ...
    def refund_generation_attempt(
        self,
        user_id: int,
        consumption: AttemptConsumption,
        *,
        error_message: str | None = None,
    ) -> None: ...
    def cleanup_stale_generations(self, now: datetime | None = None) -> int: ...
    def upsert_promo_code(self, code: str, record: PromoCodeRecord) -> None: ...
    def activate_promo_code(self, user_id: int, raw_code: str) -> PromoCodeActivation: ...
    def record_support_state(self, state: SupportState) -> None: ...
    def load_support_state(self, user_id: int) -> SupportState | None: ...
```

The production contract has these invariants:

- Every paid entitlement mutation is in a database transaction.
- Generation consumption and generation record creation happen atomically.
- Generation refund happens at most once for a generation record.
- Production never writes to JSON files.
- Support state stores operational metadata only. Do not store raw support message text in the first storage slice.
- Payment order persistence is schema-reserved and may have minimal CRUD methods, but payment application, refunds, chargebacks, and reconciliation remain separate payment-ledger work.

## Schema Contract

Create `src/diet_bot/postgres_migrations.py` with a base schema and idempotent migration runner. The first storage schema must include these tables.

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_state (
    chat_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
    state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS profiles (
    user_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
    profile_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS entitlements (
    user_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
    plan TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'inactive',
    subscription_period_start TIMESTAMPTZ,
    subscription_period_end TIMESTAMPTZ,
    test_access_until TIMESTAMPTZ,
    test_access_enabled BOOLEAN NOT NULL DEFAULT false,
    free_trial_used BOOLEAN NOT NULL DEFAULT false,
    monthly_one_day_remaining INTEGER NOT NULL DEFAULT 0,
    monthly_weekly_pdf_remaining INTEGER NOT NULL DEFAULT 0,
    extra_one_day_remaining INTEGER NOT NULL DEFAULT 0,
    extra_weekly_pdf_remaining INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (plan IN ('free', 'monthly', 'test_access')),
    CHECK (status IN ('active', 'inactive')),
    CHECK (
        monthly_one_day_remaining >= 0
        AND monthly_weekly_pdf_remaining >= 0
        AND extra_one_day_remaining >= 0
        AND extra_weekly_pdf_remaining >= 0
    )
);

CREATE TABLE IF NOT EXISTS entitlement_events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    generation_id BIGINT,
    event_type TEXT NOT NULL,
    source TEXT,
    amount INTEGER NOT NULL DEFAULT 1,
    related_event_id BIGINT REFERENCES entitlement_events(id) ON DELETE SET NULL,
    reason TEXT,
    delta_generations INTEGER,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payment_orders (
    order_id TEXT PRIMARY KEY,
    nonce TEXT NOT NULL,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    delivery_chat_id BIGINT,
    product TEXT NOT NULL,
    provider TEXT NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    invoice_link TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    paid_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (product IN ('subscription_month', 'extra_one_day', 'extra_weekly_pdf')),
    CHECK (provider IN ('telegram_stars', 'yookassa')),
    CHECK (status IN ('pending', 'paid', 'expired', 'failed_invoice_creation')),
    CHECK (amount >= 0)
);

CREATE TABLE IF NOT EXISTS generation_records (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    ration_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    entitlement_event_id BIGINT REFERENCES entitlement_events(id) ON DELETE SET NULL,
    pdf_path TEXT,
    error_message TEXT,
    heartbeat_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    delivery_started_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    telegram_message_id BIGINT,
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    CHECK (ration_kind IN ('one_day', 'weekly_pdf')),
    CHECK (status IN ('generating', 'delivering', 'completed', 'failed', 'failed_timeout')),
    CHECK (delivery_attempts >= 0)
);

CREATE TABLE IF NOT EXISTS promo_codes (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'subscription_month',
    value INTEGER NOT NULL DEFAULT 1,
    max_uses INTEGER,
    used_count INTEGER NOT NULL DEFAULT 0,
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (kind IN ('subscription_month', 'extra_one_day', 'extra_weekly_pdf', 'test_access_days')),
    CHECK (value >= 1),
    CHECK (used_count >= 0),
    CHECK (max_uses IS NULL OR max_uses >= 0),
    CHECK (max_uses IS NULL OR used_count <= max_uses)
);

CREATE TABLE IF NOT EXISTS promo_redemptions (
    id BIGSERIAL PRIMARY KEY,
    promo_code_id BIGINT NOT NULL REFERENCES promo_codes(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    redeemed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(promo_code_id, user_id)
);

CREATE TABLE IF NOT EXISTS support_state (
    user_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'idle',
    last_request_at TIMESTAMPTZ,
    last_admin_message_id BIGINT,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('idle', 'open', 'answered', 'closed'))
);
```

Required indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_entitlement_events_user_created_at
    ON entitlement_events(user_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_consume_per_generation
    ON entitlement_events(generation_id, event_type)
    WHERE event_type = 'consume' AND generation_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_refund_per_generation
    ON entitlement_events(generation_id, event_type)
    WHERE event_type = 'refund' AND generation_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_refund_per_related_event
    ON entitlement_events(related_event_id)
    WHERE event_type = 'refund' AND related_event_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_generation_per_user
    ON generation_records(user_id)
    WHERE status IN ('generating', 'delivering');

CREATE INDEX IF NOT EXISTS idx_generation_records_active_heartbeat
    ON generation_records(user_id, heartbeat_at)
    WHERE status IN ('generating', 'delivering');

CREATE INDEX IF NOT EXISTS idx_payment_orders_user_status
    ON payment_orders(user_id, status);

CREATE INDEX IF NOT EXISTS idx_promo_redemptions_user
    ON promo_redemptions(user_id, redeemed_at DESC);

CREATE INDEX IF NOT EXISTS idx_support_state_status_updated
    ON support_state(status, updated_at DESC);
```

## Idempotent Migration Rules

- `PostgresDietBotStore.initialize()` must create the migration table, apply schema statements, and record migration versions.
- Every migration version is applied at most once by `schema_migrations`.
- Use `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, and guarded `DO $$` blocks for constraints that PostgreSQL cannot create with `IF NOT EXISTS`.
- Do not use destructive migrations in the first production storage phase.
- New columns must be nullable or have safe defaults.
- A migration row is inserted after the migration statements complete.
- `initialize()` must be safe to run on every bot startup.
- Migration tests must run `initialize()` twice and verify table/index/constraint presence.

## Production Startup And JSON Fallback Rules

- Production startup succeeds only when `DIET_BOT_ENV=production` and `DIET_BOT_DATABASE_URL` is present and not an example placeholder.
- Production startup fails before constructing `Bot` if `DIET_BOT_DATABASE_URL` is missing or invalid.
- Production startup fails if `DIET_BOT_ALLOW_JSON_STORAGE=1` is the only available storage path.
- Development/local can use JSON only with explicit `DIET_BOT_ALLOW_JSON_STORAGE=1`.
- Development/local without DB and without JSON opt-in must fail with a clear storage config error.
- Healthcheck strict mode must verify PostgreSQL connectivity without importing Telegram handlers.
- JSON file paths remain local-development inputs only.

## Transaction And Locking Rules

- Set DB timeouts on every connection:
  - `connect_timeout=5`
  - `statement_timeout` default `5000ms`
  - `lock_timeout` default `1000ms`
- Use `SET statement_timeout` and `SET lock_timeout` at connection setup, or an equivalent DSN `options` value.
- No Telegram API calls, PDF generation, OpenAI calls, or network calls inside database transactions.
- Lock order for multi-row mutations:
  1. `users`
  2. `entitlements`
  3. `generation_records`
  4. `promo_codes` and `promo_redemptions`
  5. `payment_orders`
  6. `support_state`
- Entitlement mutations must select the entitlement row `FOR UPDATE`.
- Generation consumption must lock entitlement, close stale generations for that user, check the partial unique index, insert `generation_records`, insert the consume ledger event, and update entitlement in one transaction.
- Generation refund must lock entitlement and the generation record, transition only active records to failed, insert one refund event, and restore the consumed quota once.
- Promo redemption must lock entitlement and promo code rows in one transaction, insert `promo_redemptions`, increment `used_count`, and apply the promo grant once.
- Payment order placeholder methods must not lock or update entitlements.
- JSON import uses a PostgreSQL advisory lock so only one apply run can proceed.

## JSON Migration Policy

The first JSON migration slice must not claim paid-production migration readiness unless payment ledger is already implemented.

Allowed before payment ledger:

- Dry-run all known JSON inputs and produce an audit report.
- Apply only non-payment paid-state migration when the command is explicit about the limitation.
- Import profiles, chat history, entitlements, promo codes, and support state if present.
- Import `payment_orders` only as pending/invoice metadata, without applying grants.
- Import processed charge ids only as legacy duplicate metadata when explicitly limited to non-payment-ledger migration.

Blocked before payment ledger:

- Migrating live paid users for launch without payment events.
- Claiming refunds, chargebacks, orphan successful payments, or reconciliation are recoverable.
- Treating `processed_payment_charge_ids` as a full payment ledger.

The migration CLI must require one of these two modes:

```powershell
# Safe preview, writes nothing.
python scripts/migrate_json_to_postgres.py --migration-id 2026-05-12-preview --dry-run

# Apply after payment ledger exists.
python scripts/migrate_json_to_postgres.py --migration-id 2026-05-12-paid-ledger --apply --require-payment-ledger

# Limited apply before payment ledger, not valid for paid launch.
python scripts/migrate_json_to_postgres.py --migration-id 2026-05-12-limited --apply --scope non_payment_state_only --acknowledge-no-payment-ledger
```

## Implementation Tasks

### Task 1: Postgres Test Lane Guard

**Files:**

- Modify: `pyproject.toml`
- Create: `tests/conftest.py`
- Create: `tests/test_postgres_test_lane.py`

- [ ] **Step 1: Write failing tests for the marker and option**

```python
from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_declares_postgres_integration_marker() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    markers = data["tool"]["pytest"]["ini_options"]["markers"]
    assert any(marker.startswith("postgres_integration:") for marker in markers)


def test_conftest_registers_require_postgres_option() -> None:
    text = Path("tests/conftest.py").read_text(encoding="utf-8")
    assert "--require-postgres" in text
    assert "postgres_integration" in text
```

- [ ] **Step 2: Run the targeted test and verify it fails**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_postgres_test_lane.py
```

Expected: fail because `postgres_integration` and `--require-postgres` are not declared yet.

- [ ] **Step 3: Add marker and skip-safe option**

`tests/conftest.py` should add `--require-postgres` and skip `postgres_integration` tests by default.

```python
from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-postgres",
        action="store_true",
        default=False,
        help="Run PostgreSQL integration tests instead of skip-marking them.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--require-postgres"):
        return
    skip_postgres = pytest.mark.skip(reason="requires --require-postgres and DIET_BOT_TEST_DATABASE_URL")
    for item in items:
        if "postgres_integration" in item.keywords:
            item.add_marker(skip_postgres)
```

- [ ] **Step 4: Run marker tests and collect-only**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_postgres_test_lane.py
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest --collect-only -q -p no:cacheprovider
```

Expected: marker test passes and collect-only succeeds.

**Planned commit boundary:** `test: add postgres integration lane guard`

### Task 2: Storage Contract And Runtime Storage Config

**Files:**

- Create: `src/diet_bot/storage.py`
- Modify: `src/diet_bot/runtime_config.py`
- Create: `tests/test_storage_contract.py`
- Modify: `tests/test_runtime_config.py`

- [ ] **Step 1: Write failing contract/config tests**

Test names:

- `test_storage_contract_exposes_paid_production_methods`
- `test_runtime_config_accepts_production_only_with_database_url`
- `test_runtime_config_rejects_production_json_only`
- `test_runtime_config_requires_explicit_json_fallback_in_development`
- `test_runtime_config_rejects_placeholder_database_url_without_leaking_secrets`

- [ ] **Step 2: Run targeted tests and verify failures**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_storage_contract.py tests/test_runtime_config.py
```

Expected: fail because the storage protocol and database-url config are not present.

- [ ] **Step 3: Add the protocol and config fields**

`RuntimeConfig` should gain:

```python
database_url: str
local_json_storage_allowed: bool
postgres_statement_timeout_ms: int
postgres_lock_timeout_ms: int
```

Production config with a non-placeholder `DIET_BOT_DATABASE_URL` should pass config parsing, but Telegram production startup will remain blocked until Task 8 wires the store.

- [ ] **Step 4: Run targeted config/contract tests**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_storage_contract.py tests/test_runtime_config.py
```

Expected: targeted tests pass.

**Planned commit boundary:** `storage: define production storage contract`

### Task 3: Idempotent PostgreSQL Migrations

**Files:**

- Create: `src/diet_bot/postgres_migrations.py`
- Create: `tests/test_postgres_migrations.py`

- [ ] **Step 1: Write migration unit tests with a fake cursor**

Test names:

- `test_migrations_create_schema_migrations_first`
- `test_migrations_include_required_paid_storage_tables`
- `test_migrations_use_idempotent_sql_shapes`
- `test_run_postgres_migrations_records_each_version_once`

- [ ] **Step 2: Run migration tests and verify failures**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_postgres_migrations.py
```

Expected: fail because `postgres_migrations.py` does not exist.

- [ ] **Step 3: Add migration module**

Use a `PostgresMigration` dataclass and `run_postgres_migrations(cur)` function. Include the schema and indexes listed in this plan.

- [ ] **Step 4: Run migration tests**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_postgres_migrations.py
```

Expected: migration unit tests pass.

**Planned commit boundary:** `storage: add idempotent postgres migrations`

### Task 4: PostgreSQL Store Connection And Core State

**Files:**

- Modify: `pyproject.toml`
- Create: `src/diet_bot/postgres_store.py`
- Create: `tests/test_postgres_store.py`

- [ ] **Step 1: Write integration tests for connection, initialization, users, profiles, and chat state**

Mark the file with `pytestmark = pytest.mark.postgres_integration`.

Test names:

- `test_postgres_initialize_is_idempotent_and_records_migrations`
- `test_postgres_connection_applies_statement_and_lock_timeouts`
- `test_postgres_remember_user_upserts_last_seen`
- `test_postgres_profile_round_trips_json`
- `test_postgres_chat_state_round_trips_recent_history`

- [ ] **Step 2: Run skip-safe lane**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m postgres_integration
```

Expected: tests skip without `--require-postgres`.

- [ ] **Step 3: Run real DB lane and verify failures**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
$env:DIET_BOT_TEST_DATABASE_URL = "postgresql://diet_bot@localhost:5432/diet_bot_test"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m postgres_integration --require-postgres tests/test_postgres_store.py
Remove-Item Env:\DIET_BOT_TEST_DATABASE_URL
```

Expected: fail until `PostgresDietBotStore` exists. If no local test DB exists, leave this lane as not run and document that status in the implementation summary.

- [ ] **Step 4: Add `psycopg[binary]` and implement the smallest store core**

`PostgresDietBotStore.__init__` should accept:

```python
def __init__(
    self,
    dsn: str,
    *,
    connect_timeout: int = 5,
    statement_timeout_ms: int = 5000,
    lock_timeout_ms: int = 1000,
    connect_attempts: int = 1,
) -> None: ...
```

- [ ] **Step 5: Run targeted unit and integration lanes**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_postgres_migrations.py
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m postgres_integration
```

Expected: migration tests pass and integration tests skip without DB.

**Planned commit boundary:** `storage: add postgres store core`

### Task 5: Entitlements And Generation Lifecycle

**Files:**

- Modify: `src/diet_bot/postgres_store.py`
- Modify: `tests/test_postgres_store.py`

- [ ] **Step 1: Write failing integration tests**

Test names:

- `test_postgres_entitlement_round_trips_existing_model`
- `test_postgres_generation_consumption_and_refund_are_atomic`
- `test_postgres_one_active_generation_per_user`
- `test_postgres_stale_generation_cleanup_refunds_once`
- `test_postgres_completed_generation_is_not_refunded_by_late_failure`

- [ ] **Step 2: Run real DB lane and verify failures**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
$env:DIET_BOT_TEST_DATABASE_URL = "postgresql://diet_bot@localhost:5432/diet_bot_test"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m postgres_integration --require-postgres tests/test_postgres_store.py
Remove-Item Env:\DIET_BOT_TEST_DATABASE_URL
```

Expected: new tests fail until entitlement and generation methods are implemented.

- [ ] **Step 3: Implement entitlement and generation methods**

Use existing pure functions from `src/diet_bot/subscriptions.py`; do not duplicate monthly-limit arithmetic in SQL.

- [ ] **Step 4: Run storage integration and fast lanes**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m postgres_integration
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder and not postgres_integration"
```

Expected: integration skip-safe lane skips without DB and fast lane passes.

**Planned commit boundary:** `storage: persist entitlements and generation locks`

### Task 6: Promo Codes, Support State, And Payment Orders Reservation

**Files:**

- Modify: `src/diet_bot/postgres_store.py`
- Modify: `tests/test_postgres_store.py`

- [ ] **Step 1: Write failing integration tests**

Test names:

- `test_postgres_promo_redemption_is_one_per_user_and_respects_max_uses`
- `test_postgres_support_state_round_trips_without_raw_message_text`
- `test_postgres_payment_order_placeholder_round_trips_without_entitlement_change`

- [ ] **Step 2: Run real DB lane and verify failures**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
$env:DIET_BOT_TEST_DATABASE_URL = "postgresql://diet_bot@localhost:5432/diet_bot_test"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m postgres_integration --require-postgres tests/test_postgres_store.py
Remove-Item Env:\DIET_BOT_TEST_DATABASE_URL
```

Expected: fail until methods are implemented.

- [ ] **Step 3: Implement promo/support/order persistence**

Keep payment order methods limited to create, read, mark invoice link, mark expired, and mark invoice-creation failure. Do not apply payments or update entitlements from payment orders in this task.

- [ ] **Step 4: Run targeted lanes**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m postgres_integration
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_promo_codes.py tests/test_subscriptions.py
```

Expected: skip-safe integration lane skips without DB, and existing promo/subscription unit tests pass.

**Planned commit boundary:** `storage: persist promo support and payment order reservation`

### Task 7: Dev-Only JSON Store Hardening

**Files:**

- Create: `src/diet_bot/json_storage.py`
- Create: `tests/test_json_storage.py`
- Modify: `src/diet_bot/runtime_config.py`
- Modify: `tests/test_runtime_config.py`

- [ ] **Step 1: Write failing tests**

Test names:

- `test_json_storage_transaction_is_reentrant`
- `test_json_storage_lock_timeout_raises_clear_error`
- `test_json_storage_atomic_write_uses_temp_file_replace`
- `test_json_fallback_requires_explicit_development_opt_in`
- `test_production_rejects_json_fallback_even_when_flag_is_set`

- [ ] **Step 2: Run targeted tests and verify failures**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_json_storage.py tests/test_runtime_config.py
```

Expected: fail until bounded JSON storage helper exists.

- [ ] **Step 3: Implement JSON transaction helper**

The helper should expose:

```python
def json_storage_transaction(*paths: Path, timeout_seconds: float = 2.0) -> Iterator[None]: ...
def atomic_write_json(path: Path, payload: object) -> None: ...
```

- [ ] **Step 4: Run targeted tests**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_json_storage.py tests/test_runtime_config.py
```

Expected: targeted tests pass.

**Planned commit boundary:** `storage: keep json fallback dev only`

### Task 8: Runtime Wiring And Production Startup

**Files:**

- Modify: `src/diet_bot/telegram_app.py`
- Modify: `src/diet_bot/healthcheck.py`
- Create: `tests/test_storage_config.py`
- Modify: `tests/test_healthcheck.py`
- Modify: `tests/test_telegram_app_runtime.py`

- [ ] **Step 1: Write failing tests**

Test names:

- `test_production_without_database_url_does_not_construct_bot`
- `test_production_with_database_url_initializes_postgres_store_before_polling`
- `test_development_can_use_json_storage_fallback_when_flag_is_set`
- `test_development_without_json_storage_flag_rejects_fallback`
- `test_healthcheck_strict_requires_postgres_in_production`

- [ ] **Step 2: Run targeted tests and verify failures**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_storage_config.py tests/test_healthcheck.py tests/test_telegram_app_runtime.py
```

Expected: fail until runtime uses the storage contract.

- [ ] **Step 3: Wire storage through small adapter functions**

Change only storage access points:

- `_load_chat_history`
- `_save_chat_history`
- `_profile_for_chat`
- `_save_chat_profile`
- `_entitlement_for_chat`
- `_consume_generation_attempt`
- `_refund_generation_attempt`
- promo activation persistence
- support state persistence
- startup store validation

Do not change invoice payloads, successful-payment application, refund handling, PDF layout, or subscription business rules in this task.

- [ ] **Step 4: Run targeted runtime/storage tests**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_storage_config.py tests/test_healthcheck.py tests/test_telegram_app_runtime.py tests/test_telegram_app_photos.py
```

Expected: targeted runtime tests pass.

**Planned commit boundary:** `storage: wire postgres store into runtime startup`

### Task 9: JSON-To-Postgres Migration With Explicit Limitation

**Files:**

- Create: `scripts/migrate_json_to_postgres.py`
- Create: `tests/test_json_to_postgres_migration.py`

- [ ] **Step 1: Write failing migration tests**

Test names:

- `test_migration_dry_run_writes_nothing`
- `test_migration_apply_is_one_shot_by_migration_id`
- `test_migration_imports_history_profiles_entitlements_and_promo_codes`
- `test_migration_blocks_paid_launch_without_payment_ledger_ack`
- `test_migration_limited_mode_reports_non_payment_state_only`
- `test_migration_imports_payment_orders_as_metadata_without_granting_access`

- [ ] **Step 2: Run migration tests and verify failures**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_json_to_postgres_migration.py
```

Expected: fail because migration CLI does not exist.

- [ ] **Step 3: Implement migration CLI**

The command must default to dry-run. Apply mode must require either `--require-payment-ledger` or the explicit limited-mode pair `--scope non_payment_state_only --acknowledge-no-payment-ledger`.

- [ ] **Step 4: Run migration tests and skip-safe Postgres lane**

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider tests/test_json_to_postgres_migration.py
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m postgres_integration
```

Expected: migration unit tests pass and integration lane skips without DB.

**Planned commit boundary:** `storage: add guarded json to postgres migration`

## Verification Commands

Fast gate after each slice:

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
git status --short --branch
git diff --stat
git diff --check
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m "not slow_pdf_builder and not postgres_integration"
```

Postgres skip-safe lane:

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m postgres_integration
```

Postgres integration lane with real DB:

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
$env:DIET_BOT_TEST_DATABASE_URL = "postgresql://diet_bot@localhost:5432/diet_bot_test"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider -m postgres_integration --require-postgres tests/test_postgres_store.py tests/test_json_to_postgres_migration.py
Remove-Item Env:\DIET_BOT_TEST_DATABASE_URL
```

Full local suite when the slice is not time-sensitive:

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider
```

Production config smoke after runtime wiring:

```powershell
cd "C:\Users\adck8\Documents\New project 2 CLEAN"
$env:DIET_BOT_ENV = "production"
$env:DIET_BOT_TOKEN = "healthcheck-local-token"
$env:DIET_BOT_DATABASE_URL = "postgresql://diet_bot@localhost:5432/diet_bot_test"
& "C:\Users\adck8\Documents\New project 2\.venv\Scripts\python.exe" -B -m diet_bot.healthcheck --strict
Remove-Item Env:\DIET_BOT_ENV
Remove-Item Env:\DIET_BOT_TOKEN
Remove-Item Env:\DIET_BOT_DATABASE_URL
```

## Planned Commit Boundaries

1. `test: add postgres integration lane guard`
   - `pyproject.toml`
   - `tests/conftest.py`
   - `tests/test_postgres_test_lane.py`

2. `storage: define production storage contract`
   - `src/diet_bot/storage.py`
   - `src/diet_bot/runtime_config.py`
   - `tests/test_storage_contract.py`
   - `tests/test_runtime_config.py`

3. `storage: add idempotent postgres migrations`
   - `src/diet_bot/postgres_migrations.py`
   - `tests/test_postgres_migrations.py`

4. `storage: add postgres store core`
   - `pyproject.toml`
   - `src/diet_bot/postgres_store.py`
   - `tests/test_postgres_store.py`

5. `storage: persist entitlements and generation locks`
   - `src/diet_bot/postgres_store.py`
   - `tests/test_postgres_store.py`

6. `storage: persist promo support and payment order reservation`
   - `src/diet_bot/postgres_store.py`
   - `tests/test_postgres_store.py`

7. `storage: keep json fallback dev only`
   - `src/diet_bot/json_storage.py`
   - `src/diet_bot/runtime_config.py`
   - `tests/test_json_storage.py`
   - `tests/test_runtime_config.py`

8. `storage: wire postgres store into runtime startup`
   - `src/diet_bot/telegram_app.py`
   - `src/diet_bot/healthcheck.py`
   - `tests/test_storage_config.py`
   - `tests/test_healthcheck.py`
   - `tests/test_telegram_app_runtime.py`

9. `storage: add guarded json to postgres migration`
   - `scripts/migrate_json_to_postgres.py`
   - `tests/test_json_to_postgres_migration.py`

## First Small Implementation Task

Start with Task 1 only:

- [ ] Confirm the guard command still reports branch `codex/emergency-stabilization`.
- [ ] Add `tests/test_postgres_test_lane.py` with marker and option assertions.
- [ ] Run the targeted test and confirm it fails.
- [ ] Add the `postgres_integration` marker to `pyproject.toml`.
- [ ] Add `tests/conftest.py` with `--require-postgres` skip-safe behavior.
- [ ] Run `tests/test_postgres_test_lane.py`.
- [ ] Run `pytest --collect-only`.
- [ ] Run the fast gate.
- [ ] Stop for review before adding any storage production code.

## Self-Review

- Spec coverage: includes paid-production storage contract, users/profiles/entitlements/payment-orders placeholder/generation/promo/support schema, idempotent migrations, production Postgres startup, dev-only JSON fallback, JSON migration limitation, transaction and locking rules, tests-first slices, fast/Postgres commands, and commit boundaries.
- Scope check: excludes payment business logic, refund/chargeback/reconciliation, full old `postgres_store.py`, full old `telegram_app.py`, Docker/CI workflows, and production deploy changes.
- Placeholder scan: the only planned placeholder is the requested `payment_orders` storage reservation; it has concrete schema, methods, tests, and boundaries.
