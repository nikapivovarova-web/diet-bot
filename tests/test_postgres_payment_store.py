from __future__ import annotations

import os
import re
import shlex
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse

import pytest

import diet_bot.postgres_payment_store as postgres_payment_store
from diet_bot.payments import (
    ORDER_STATUS_FAILED,
    ORDER_STATUS_GRANTED,
    ORDER_STATUS_PAID,
    ORDER_STATUS_PENDING,
    PRODUCT_EXTRA_WEEKLY_PDF,
    PRODUCT_SUBSCRIPTION_MONTH,
    PROVIDER_TELEGRAM_STARS,
    PROVIDER_YOOKASSA,
    PaymentCharge,
    PaymentEvent,
    PaymentOrder,
)
from diet_bot.postgres_entitlement_store import PostgresEntitlementStore
from diet_bot.postgres_payment_store import PostgresPaymentStore
from diet_bot.subscriptions import MONTHLY_ONE_DAY_LIMIT, MONTHLY_WEEKLY_PDF_LIMIT


TEST_DATABASE_URL = os.getenv("DIET_BOT_TEST_DATABASE_URL")

pytestmark = pytest.mark.postgres_integration


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://user:pass@db.example.com/diet_bot",
        "postgresql://user:pass@db.example.com/postgres",
        "postgresql://user:pass@db.example.com/production",
        "postgresql://user:pass@db.example.com/latest",
        "postgresql://user:pass@db.example.com/contest_prod",
        "dbname=diet_bot_prod user=diet_bot",
        "dbname=latest user=diet_bot",
        "dbname=production_testimonial user=diet_bot",
    ],
)
def test_test_database_url_guard_rejects_production_looking_urls(database_url: str) -> None:
    with pytest.raises(ValueError, match="DIET_BOT_TEST_DATABASE_URL"):
        _require_safe_test_database_url(database_url)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://user:pass@localhost/test",
        "postgresql://user:pass@localhost/payment_ledger_test",
        "postgresql://user:pass@localhost/diet_bot_test",
        "postgresql://user:pass@localhost/postgres?options=-csearch_path%3Ddiet_bot_test",
        "postgresql://user:pass@localhost/postgres?search_path=payment-ledger-test",
        "dbname=test user=diet_bot",
        "dbname=payment_ledger_test user=diet_bot",
    ],
)
def test_test_database_url_guard_accepts_test_database_or_schema(database_url: str) -> None:
    _require_safe_test_database_url(database_url)


def test_record_charge_returns_existing_row_after_insert_conflict() -> None:
    existing_row = _charge_row(
        charge_id=42,
        order_id="order_charge_race",
        provider=PROVIDER_TELEGRAM_STARS,
        telegram_payment_charge_id="tg-charge-race",
        provider_payment_charge_id=None,
        amount=400,
        currency="XTR",
    )
    cur = RaceConflictCursor(existing_row)
    store = PostgresPaymentStore("postgresql://example/test")

    recorded = store._record_charge_cur(
        cur,
        PaymentCharge(
            order_id="order_charge_race",
            provider=PROVIDER_TELEGRAM_STARS,
            telegram_payment_charge_id="tg-charge-race",
            provider_payment_charge_id=None,
            amount=400,
            currency="XTR",
        ),
    )

    assert not recorded.inserted
    assert recorded.charge.charge_id == 42
    assert any("INSERT INTO payment_charges" in query and "ON CONFLICT DO NOTHING" in query for query in cur.queries)


def test_record_event_returns_existing_row_after_event_key_insert_conflict() -> None:
    existing_row = _event_row(
        event_id="event_existing",
        event_type="successful_payment_received",
        order_id="order_event_race",
        provider=PROVIDER_TELEGRAM_STARS,
        event_key="telegram_stars:tg-event-race:received",
        telegram_payment_charge_id="tg-event-race",
        provider_payment_charge_id=None,
        payload_json={"ok": True},
    )
    cur = RaceConflictCursor(existing_row)
    store = PostgresPaymentStore("postgresql://example/test")

    event = store._record_event_cur(
        cur,
        PaymentEvent(
            event_id="event_new",
            event_type="successful_payment_received",
            order_id="order_event_race",
            provider=PROVIDER_TELEGRAM_STARS,
            event_key="telegram_stars:tg-event-race:received",
            telegram_payment_charge_id="tg-event-race",
            payload={"ok": True},
        ),
    )

    assert event.event_id == "event_existing"
    assert any("INSERT INTO payment_events" in query and "ON CONFLICT DO NOTHING" in query for query in cur.queries)


def test_load_entitlement_creates_missing_row_before_locking() -> None:
    cur = MissingEntitlementCursor()

    entitlement = postgres_payment_store._load_entitlement_cur(cur, 202)

    normalized_queries = [" ".join(query.split()) for query in cur.queries]
    assert normalized_queries[0].startswith("INSERT INTO entitlements")
    assert "ON CONFLICT (chat_id) DO NOTHING" in normalized_queries[0]
    assert normalized_queries[1].startswith("SELECT")
    assert "FROM entitlements" in normalized_queries[1]
    assert "FOR UPDATE" in normalized_queries[1]
    assert entitlement.processed_payment_charge_ids == []


@pytest.fixture
def store() -> PostgresPaymentStore:
    if not TEST_DATABASE_URL:
        pytest.skip("set DIET_BOT_TEST_DATABASE_URL to run Postgres payment integration tests")
    try:
        _require_safe_test_database_url(TEST_DATABASE_URL)
    except ValueError as exc:
        pytest.fail(str(exc))

    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema_name = f"diet_bot_test_{uuid.uuid4().hex}"
    admin_dsn = make_conninfo(TEST_DATABASE_URL, connect_timeout="1")
    try:
        _create_test_schema(psycopg, sql, admin_dsn, schema_name)
    except Exception as exc:
        pytest.fail(f"Postgres test database schema setup failed: {exc}")

    scoped_dsn = make_conninfo(
        TEST_DATABASE_URL,
        connect_timeout="1",
        options=f"-c search_path={schema_name}",
    )
    candidate = PostgresPaymentStore(scoped_dsn, connect_timeout=1, connect_attempts=1)
    try:
        candidate.initialize()
    except Exception as exc:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)
        pytest.fail(f"Postgres payment test database initialization failed: {exc}")
    try:
        yield candidate
    finally:
        _drop_test_schema(psycopg, sql, admin_dsn, schema_name)


def test_schema_init_is_idempotent(store: PostgresPaymentStore) -> None:
    store.initialize()
    store.initialize()
    store.validate_schema()

    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name IN (
                    'schema_migrations',
                    'payment_orders',
                    'payment_charges',
                    'payment_events'
                  )
                """
            )
            tables = {row["table_name"] for row in cur.fetchall()}
            cur.execute(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conname IN (
                    'chk_payment_orders_product',
                    'chk_payment_orders_provider',
                    'chk_payment_orders_status',
                    'chk_payment_charges_provider',
                    'chk_payment_charges_status',
                    'chk_payment_events_type'
                )
                """
            )
            constraints = {row["conname"] for row in cur.fetchall()}
            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname IN (
                    'idx_payment_charges_telegram_charge_id_unique',
                    'idx_payment_charges_provider_charge_id_unique',
                    'idx_payment_events_event_key_unique'
                  )
                """
            )
            indexes = {row["indexname"] for row in cur.fetchall()}

    assert tables == {"schema_migrations", "payment_orders", "payment_charges", "payment_events"}
    assert constraints == {
        "chk_payment_orders_product",
        "chk_payment_orders_provider",
        "chk_payment_orders_status",
        "chk_payment_charges_provider",
        "chk_payment_charges_status",
        "chk_payment_events_type",
    }
    assert indexes == {
        "idx_payment_charges_telegram_charge_id_unique",
        "idx_payment_charges_provider_charge_id_unique",
        "idx_payment_events_event_key_unique",
    }


def test_validate_schema_rejects_missing_critical_index(store: PostgresPaymentStore) -> None:
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP INDEX idx_payment_events_order_created")

    with pytest.raises(RuntimeError, match="missing indexes.*idx_payment_events_order_created"):
        store.validate_schema()


def test_order_lifecycle(store: PostgresPaymentStore) -> None:
    order = store.create_order(_order("order_lifecycle123", PRODUCT_SUBSCRIPTION_MONTH))

    assert store.get_order(order.order_id) == order
    assert store.mark_order_paid(order.order_id).status == ORDER_STATUS_PAID
    assert store.mark_order_granted(order.order_id).status == ORDER_STATUS_GRANTED

    failed = store.create_order(_order("order_failed123456", PRODUCT_EXTRA_WEEKLY_PDF))
    marked_failed = store.mark_order_failed(failed.order_id, "provider_rejected")

    assert marked_failed.status == ORDER_STATUS_FAILED
    assert marked_failed.failure_reason == "provider_rejected"


def test_charge_and_event_recording_are_idempotent(store: PostgresPaymentStore) -> None:
    order = store.create_order(_order("order_charge12345", PRODUCT_SUBSCRIPTION_MONTH))
    event = PaymentEvent(
        event_id="event_1234567890",
        event_type="successful_payment_received",
        order_id=order.order_id,
        provider=PROVIDER_TELEGRAM_STARS,
        event_key="telegram_stars:tg-charge-1:received",
        telegram_payment_charge_id="tg-charge-1",
        payload={"ok": True},
    )

    first_event = store.record_event(event)
    second_event = store.record_event(event)
    first_charge = store.record_charge(
        PaymentCharge(
            order_id=order.order_id,
            provider=PROVIDER_TELEGRAM_STARS,
            telegram_payment_charge_id="tg-charge-1",
            provider_payment_charge_id=None,
            amount=400,
            currency="XTR",
            raw_payload={"ok": True},
        )
    )
    second_charge = store.record_charge(
        PaymentCharge(
            order_id=order.order_id,
            provider=PROVIDER_TELEGRAM_STARS,
            telegram_payment_charge_id="tg-charge-1",
            provider_payment_charge_id=None,
            amount=400,
            currency="XTR",
            raw_payload={"ok": True},
        )
    )

    assert first_event == second_event
    assert first_charge.inserted
    assert not second_charge.inserted
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS count FROM payment_events")
            assert int(cur.fetchone()["count"]) == 1
            cur.execute("SELECT count(*) AS count FROM payment_charges")
            assert int(cur.fetchone()["count"]) == 1


def test_duplicate_provider_charge_is_not_inserted_twice(store: PostgresPaymentStore) -> None:
    first_order = store.create_order(_order("order_provider1", PRODUCT_SUBSCRIPTION_MONTH, provider=PROVIDER_YOOKASSA))
    second_order = store.create_order(_order("order_provider2", PRODUCT_EXTRA_WEEKLY_PDF, provider=PROVIDER_YOOKASSA))

    first = store.record_charge(
        PaymentCharge(
            order_id=first_order.order_id,
            provider=PROVIDER_YOOKASSA,
            telegram_payment_charge_id="tg-charge-yoo-1",
            provider_payment_charge_id="provider-charge-1",
            amount=59_900,
            currency="RUB",
        )
    )
    duplicate = store.record_charge(
        PaymentCharge(
            order_id=second_order.order_id,
            provider=PROVIDER_YOOKASSA,
            telegram_payment_charge_id="tg-charge-yoo-2",
            provider_payment_charge_id="provider-charge-1",
            amount=25_000,
            currency="RUB",
        )
    )

    assert first.inserted
    assert not duplicate.inserted
    assert duplicate.charge.order_id == first_order.order_id
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS count FROM payment_charges")
            assert int(cur.fetchone()["count"]) == 1


def test_successful_payment_transaction_rolls_back_if_entitlement_grant_fails(
    store: PostgresPaymentStore,
) -> None:
    order = store.create_order(_order("order_rollback123", PRODUCT_SUBSCRIPTION_MONTH))

    def fail_grant(_cur: object, _order: PaymentOrder, _charge: PaymentCharge) -> None:
        raise RuntimeError("grant failed")

    with pytest.raises(RuntimeError, match="grant failed"):
        store.record_successful_payment_and_grant_entitlement(
            order_id=order.order_id,
            provider=PROVIDER_TELEGRAM_STARS,
            telegram_payment_charge_id="tg-charge-rollback",
            provider_payment_charge_id=None,
            amount=400,
            currency="XTR",
            grant_entitlement=fail_grant,
        )

    assert store.get_order(order.order_id).status == ORDER_STATUS_PENDING
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS count FROM payment_charges")
            assert int(cur.fetchone()["count"]) == 0


def test_successful_payment_transaction_grants_entitlement_tables(
    store: PostgresPaymentStore,
) -> None:
    PostgresEntitlementStore(store.dsn, connect_timeout=1, connect_attempts=1).initialize()
    now = datetime(2026, 5, 22, tzinfo=UTC)
    order = store.create_order(_order("order_grant12345", PRODUCT_SUBSCRIPTION_MONTH))

    result = store.record_successful_payment_and_grant_entitlement(
        order_id=order.order_id,
        provider=PROVIDER_TELEGRAM_STARS,
        telegram_payment_charge_id="tg-charge-grant",
        provider_payment_charge_id=None,
        amount=400,
        currency="XTR",
        now=now,
        subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
    )

    assert result.inserted
    assert store.get_order(order.order_id).status == ORDER_STATUS_GRANTED
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT monthly_one_day_remaining, monthly_weekly_pdf_remaining
                FROM entitlements
                WHERE chat_id = %s
                """,
                (order.chat_id,),
            )
            entitlement = cur.fetchone()
            cur.execute(
                """
                SELECT charge_id
                FROM entitlement_processed_charge_ids
                WHERE chat_id = %s
                """,
                (order.chat_id,),
            )
            charge_ids = {row["charge_id"] for row in cur.fetchall()}

    assert int(entitlement["monthly_one_day_remaining"]) == MONTHLY_ONE_DAY_LIMIT
    assert int(entitlement["monthly_weekly_pdf_remaining"]) == MONTHLY_WEEKLY_PDF_LIMIT
    assert charge_ids == {"telegram_stars:tg-charge-grant"}


def test_concurrent_successful_payments_for_same_new_chat_preserve_both_grants(
    store: PostgresPaymentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    PostgresEntitlementStore(store.dsn, connect_timeout=1, connect_attempts=1).initialize()
    now = datetime(2026, 5, 22, tzinfo=UTC)
    subscription_order = store.create_order(_order("order_concur_sub", PRODUCT_SUBSCRIPTION_MONTH))
    extra_order = store.create_order(_order("order_concur_pdf", PRODUCT_EXTRA_WEEKLY_PDF))
    charge_ids = {
        subscription_order.order_id: "tg-charge-concur-sub",
        extra_order.order_id: "tg-charge-concur-pdf",
    }
    load_barrier = threading.Barrier(2)
    original_load_entitlement = postgres_payment_store._load_entitlement_cur

    def wait_after_empty_entitlement_load(cur: object, chat_id: int):
        entitlement = original_load_entitlement(cur, chat_id)
        if int(chat_id) == subscription_order.chat_id and not entitlement.processed_payment_charge_ids:
            try:
                load_barrier.wait(timeout=1)
            except threading.BrokenBarrierError:
                pass
        return entitlement

    monkeypatch.setattr(postgres_payment_store, "_load_entitlement_cur", wait_after_empty_entitlement_load)

    def record(order: PaymentOrder):
        return store.record_successful_payment_and_grant_entitlement(
            order_id=order.order_id,
            provider=PROVIDER_TELEGRAM_STARS,
            telegram_payment_charge_id=charge_ids[order.order_id],
            provider_payment_charge_id=None,
            amount=order.amount,
            currency=order.currency,
            product=order.product,
            now=now,
            subscription_expiration_timestamp=int((now + timedelta(days=30)).timestamp()),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(record, subscription_order),
            executor.submit(record, extra_order),
        ]
        results = [future.result(timeout=10) for future in futures]

    assert [result.inserted for result in results] == [True, True]
    assert store.get_order(subscription_order.order_id).status == ORDER_STATUS_GRANTED
    assert store.get_order(extra_order.order_id).status == ORDER_STATUS_GRANTED
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT monthly_one_day_remaining, monthly_weekly_pdf_remaining, extra_weekly_pdf_remaining
                FROM entitlements
                WHERE chat_id = %s
                """,
                (subscription_order.chat_id,),
            )
            entitlement = cur.fetchone()
            cur.execute(
                """
                SELECT charge_id
                FROM entitlement_processed_charge_ids
                WHERE chat_id = %s
                ORDER BY position
                """,
                (subscription_order.chat_id,),
            )
            processed_charge_ids = [row["charge_id"] for row in cur.fetchall()]

    assert int(entitlement["monthly_one_day_remaining"]) == MONTHLY_ONE_DAY_LIMIT
    assert int(entitlement["monthly_weekly_pdf_remaining"]) == MONTHLY_WEEKLY_PDF_LIMIT
    assert int(entitlement["extra_weekly_pdf_remaining"]) == 1
    assert set(processed_charge_ids) == {
        "telegram_stars:tg-charge-concur-sub",
        "telegram_stars:tg-charge-concur-pdf",
    }


def test_successful_payment_transaction_duplicate_same_charge_is_idempotent(
    store: PostgresPaymentStore,
) -> None:
    PostgresEntitlementStore(store.dsn, connect_timeout=1, connect_attempts=1).initialize()
    order = store.create_order(_order("order_same_charge", PRODUCT_EXTRA_WEEKLY_PDF))
    request = {
        "order_id": order.order_id,
        "provider": PROVIDER_TELEGRAM_STARS,
        "telegram_payment_charge_id": "tg-charge-same",
        "provider_payment_charge_id": None,
        "amount": order.amount,
        "currency": order.currency,
        "product": order.product,
    }

    first = store.record_successful_payment_and_grant_entitlement(**request)
    second = store.record_successful_payment_and_grant_entitlement(**request)

    assert first.inserted
    assert not second.inserted
    assert second.reason == "duplicate_charge"
    assert store.get_order(order.order_id).status == ORDER_STATUS_GRANTED
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT extra_weekly_pdf_remaining
                FROM entitlements
                WHERE chat_id = %s
                """,
                (order.chat_id,),
            )
            entitlement = cur.fetchone()
            cur.execute(
                """
                SELECT charge_id
                FROM entitlement_processed_charge_ids
                WHERE chat_id = %s
                """,
                (order.chat_id,),
            )
            processed_charge_ids = [row["charge_id"] for row in cur.fetchall()]
            cur.execute("SELECT count(*) AS count FROM payment_charges")
            charge_count = int(cur.fetchone()["count"])

    assert int(entitlement["extra_weekly_pdf_remaining"]) == 1
    assert processed_charge_ids == ["telegram_stars:tg-charge-same"]
    assert charge_count == 1


def test_successful_payment_transaction_rejects_new_charge_for_granted_order(
    store: PostgresPaymentStore,
) -> None:
    grants: list[str] = []
    order = store.create_order(_order("order_granted_dupe", PRODUCT_SUBSCRIPTION_MONTH))

    first = store.record_successful_payment_and_grant_entitlement(
        order_id=order.order_id,
        provider=PROVIDER_TELEGRAM_STARS,
        telegram_payment_charge_id="tg-charge-first",
        provider_payment_charge_id=None,
        amount=400,
        currency="XTR",
        grant_entitlement=lambda _cur, _order, charge: grants.append(str(charge.telegram_payment_charge_id)),
    )
    second = store.record_successful_payment_and_grant_entitlement(
        order_id=order.order_id,
        provider=PROVIDER_TELEGRAM_STARS,
        telegram_payment_charge_id="tg-charge-second",
        provider_payment_charge_id=None,
        amount=400,
        currency="XTR",
        grant_entitlement=lambda _cur, _order, charge: grants.append(str(charge.telegram_payment_charge_id)),
    )

    assert first.inserted
    assert not second.inserted
    assert second.reason == "order_not_payable"
    assert grants == ["tg-charge-first"]
    assert store.get_order(order.order_id).status == ORDER_STATUS_GRANTED
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS count FROM payment_charges")
            assert int(cur.fetchone()["count"]) == 1


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"provider": PROVIDER_YOOKASSA}, "provider_mismatch"),
        ({"amount": 401}, "amount_mismatch"),
        ({"currency": "RUB"}, "currency_mismatch"),
    ],
)
def test_successful_payment_transaction_rejects_mismatched_payment_context(
    store: PostgresPaymentStore,
    override: dict[str, object],
    reason: str,
) -> None:
    grants: list[str] = []
    order = store.create_order(_order("order_context_bad", PRODUCT_SUBSCRIPTION_MONTH))
    request: dict[str, object] = {
        "order_id": order.order_id,
        "provider": PROVIDER_TELEGRAM_STARS,
        "telegram_payment_charge_id": "tg-charge-bad-context",
        "provider_payment_charge_id": None,
        "amount": 400,
        "currency": "XTR",
        "grant_entitlement": lambda _cur, _order, charge: grants.append(str(charge.telegram_payment_charge_id)),
    }
    request.update(override)

    result = store.record_successful_payment_and_grant_entitlement(**request)

    assert not result.inserted
    assert result.reason == reason
    assert grants == []
    failed = store.get_order(order.order_id)
    assert failed is not None
    assert failed.status == ORDER_STATUS_FAILED
    assert failed.failure_reason == reason
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS count FROM payment_charges")
            assert int(cur.fetchone()["count"]) == 0


def _order(order_id: str, product: str, *, provider: str = PROVIDER_TELEGRAM_STARS) -> PaymentOrder:
    if provider == PROVIDER_TELEGRAM_STARS:
        amount = 400 if product == PRODUCT_SUBSCRIPTION_MONTH else 170
        currency = "XTR"
    else:
        amount = 59_900 if product == PRODUCT_SUBSCRIPTION_MONTH else 25_000
        currency = "RUB"
    return PaymentOrder(
        order_id=order_id,
        user_id=101,
        chat_id=202,
        product=product,
        provider=provider,
        amount=amount,
        currency=currency,
        nonce=f"nonce_{order_id}",
    )


def _require_safe_test_database_url(database_url: str) -> None:
    names = _database_or_schema_names(database_url)
    if any(_is_explicit_test_name(name) for name in names):
        return
    raise ValueError(
        "DIET_BOT_TEST_DATABASE_URL must name an explicit test database or schema; refusing to initialize "
        "or clean up integration test tables."
    )


def _is_explicit_test_name(name: str) -> bool:
    normalized = name.strip().strip("'\"").lower()
    if normalized in {"test", "diet_bot_test", "diet-bot-test"}:
        return True
    return (
        normalized.startswith("test_")
        or normalized.endswith("_test")
        or normalized.startswith("test-")
        or normalized.endswith("-test")
        or "_test_" in normalized
        or "-test-" in normalized
    )


def _database_or_schema_names(database_url: str) -> list[str]:
    text = database_url.strip()
    names: list[str] = []
    if "://" in text:
        parsed = urlparse(text)
        database = unquote(parsed.path.lstrip("/"))
        if database:
            names.append(database)
        query = {key.lower(): value for key, value in parse_qs(parsed.query).items()}
        for option in query.get("options", []):
            names.extend(_search_path_names(option))
        for schema_key in ("search_path", "currentschema"):
            for value in query.get(schema_key, []):
                names.extend(_split_schema_names(value))
        return names

    fields = _parse_conninfo_fields(text)
    database = fields.get("dbname")
    if database:
        names.append(database)
    if "options" in fields:
        names.extend(_search_path_names(fields["options"]))
    if "search_path" in fields:
        names.extend(_split_schema_names(fields["search_path"]))
    return names


def _parse_conninfo_fields(conninfo: str) -> dict[str, str]:
    try:
        tokens = shlex.split(conninfo)
    except ValueError:
        tokens = conninfo.split()
    fields: dict[str, str] = {}
    for token in tokens:
        key, separator, value = token.partition("=")
        if separator:
            fields[key.lower()] = value
    return fields


def _search_path_names(options: str) -> list[str]:
    match = re.search(r"search_path(?:=|\s+)([^\s]+)", options, flags=re.IGNORECASE)
    if not match:
        return []
    return _split_schema_names(match.group(1))


def _split_schema_names(value: str) -> list[str]:
    names: list[str] = []
    for raw_name in value.split(","):
        name = raw_name.strip().strip("'\"")
        if name and name not in {"$user", "public"}:
            names.append(name)
    return names


def _create_test_schema(psycopg: object, sql: object, database_url: str, schema_name: str) -> None:
    _require_generated_test_schema(schema_name)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))


def _drop_test_schema(psycopg: object, sql: object, database_url: str, schema_name: str) -> None:
    _require_generated_test_schema(schema_name)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name)))


def _require_generated_test_schema(schema_name: str) -> None:
    if not re.fullmatch(r"diet_bot_test_[0-9a-f]{32}", schema_name):
        raise ValueError(f"refusing to manage unsafe test schema name: {schema_name}")


class RaceConflictCursor:
    def __init__(self, existing_row: dict[str, object]) -> None:
        self.existing_row = existing_row
        self.queries: list[str] = []
        self._next_row: dict[str, object] | None = None
        self._conflict_happened = False

    def execute(self, query: object, params: object | None = None) -> None:
        text = str(query)
        self.queries.append(text)
        normalized = " ".join(text.split())
        if normalized.startswith("SELECT"):
            if "payment_charges" in normalized or "payment_events" in normalized:
                self._next_row = self.existing_row if self._conflict_happened else None
            else:
                self._next_row = None
            return
        if "INSERT INTO payment_charges" in normalized or "INSERT INTO payment_events" in normalized:
            if "ON CONFLICT DO NOTHING" not in normalized:
                raise RuntimeError("simulated unique conflict")
            self._conflict_happened = True
            self._next_row = None
            return
        self._next_row = None

    def fetchone(self) -> dict[str, object] | None:
        row = self._next_row
        self._next_row = None
        return row


class MissingEntitlementCursor:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self._next_row: dict[str, object] | None = None
        self._next_rows: list[dict[str, object]] = []

    def execute(self, query: object, params: object | None = None) -> None:
        text = str(query)
        self.queries.append(text)
        normalized = " ".join(text.split())
        if normalized.startswith("SELECT") and "FROM entitlements" in normalized:
            self._next_row = {
                "chat_id": 202,
                "free_trial_used": False,
                "subscription_period_start": None,
                "subscription_period_end": None,
                "test_access_until": None,
                "test_access_enabled": False,
                "monthly_one_day_remaining": 0,
                "monthly_weekly_pdf_remaining": 0,
                "extra_one_day_remaining": 0,
                "extra_weekly_pdf_remaining": 0,
            }
            return
        if normalized.startswith("SELECT") and "FROM entitlement_processed_charge_ids" in normalized:
            self._next_rows = []
            return
        self._next_row = None
        self._next_rows = []

    def fetchone(self) -> dict[str, object] | None:
        row = self._next_row
        self._next_row = None
        return row

    def fetchall(self) -> list[dict[str, object]]:
        rows = self._next_rows
        self._next_rows = []
        return rows


def _charge_row(
    *,
    charge_id: int,
    order_id: str,
    provider: str,
    telegram_payment_charge_id: str | None,
    provider_payment_charge_id: str | None,
    amount: int,
    currency: str,
) -> dict[str, object]:
    return {
        "charge_id": charge_id,
        "order_id": order_id,
        "provider": provider,
        "telegram_payment_charge_id": telegram_payment_charge_id,
        "provider_payment_charge_id": provider_payment_charge_id,
        "amount": amount,
        "currency": currency,
        "status": "succeeded",
        "raw_payload_json": {},
        "created_at": datetime(2026, 5, 22, tzinfo=UTC),
    }


def _event_row(
    *,
    event_id: str,
    event_type: str,
    order_id: str,
    provider: str,
    event_key: str,
    telegram_payment_charge_id: str | None,
    provider_payment_charge_id: str | None,
    payload_json: dict[str, object],
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "order_id": order_id,
        "provider": provider,
        "event_key": event_key,
        "telegram_payment_charge_id": telegram_payment_charge_id,
        "provider_payment_charge_id": provider_payment_charge_id,
        "payload_json": payload_json,
        "created_at": datetime(2026, 5, 22, tzinfo=UTC),
    }
