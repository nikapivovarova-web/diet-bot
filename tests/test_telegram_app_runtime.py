from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import types
from datetime import UTC, datetime
from uuid import uuid4

import pytest


def _postgres_runtime_config(tmp_path):
    from diet_bot.runtime_config import load_runtime_config

    return load_runtime_config(
        {
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
            "DIET_BOT_PROMO_CODES_STATE_FILE": str(tmp_path / "promo_codes.json"),
        },
    )


def _promo_store_result(
    status: str,
    *,
    code: str = "FB-ABCD-EFGH-2345",
    chat_id: int = 80_301,
    redemption_id: int = 90_001,
):
    redemption = None
    if status in {"reserved", "redeemed", "already_redeemed"}:
        redemption = types.SimpleNamespace(
            redemption_id=redemption_id,
            code=code,
            chat_id=chat_id,
            entitlement_charge_id=None,
        )
    return types.SimpleNamespace(
        status=status,
        code=code,
        chat_id=chat_id,
        redemption=redemption,
    )


class _PostgresPromoStoreDouble:
    def __init__(self, *results) -> None:
        self.results = list(results)
        self.promos: dict[str, object] = {}
        self.init_calls: list[tuple[str, dict[str, object]]] = []
        self.get_calls: list[str] = []
        self.create_calls: list[tuple[object, dict[str, object]]] = []
        self.list_calls: list[dict[str, object]] = []
        self.disable_calls: list[tuple[str, dict[str, object]]] = []
        self.reserve_calls: list[tuple[str, dict[str, object]]] = []
        self.finalize_calls: list[tuple[int, dict[str, object]]] = []
        self.release_calls: list[tuple[int, dict[str, object]]] = []

    def get_promo_code(self, raw_code: str):
        from diet_bot.promo_codes import normalize_promo_code

        self.get_calls.append(raw_code)
        return self.promos.get(normalize_promo_code(raw_code))

    def create_or_update_promo_code(self, definition, **kwargs):
        from diet_bot.promo_codes import PromoCodeDefinition

        normalized = PromoCodeDefinition(**definition.to_dict())
        self.create_calls.append((normalized, dict(kwargs)))
        stored = _stored_promo_code(normalized, **kwargs)
        self.promos[normalized.code] = stored
        return stored

    def list_active_promo_codes(self, **kwargs):
        self.list_calls.append(dict(kwargs))
        return [
            promo
            for promo in sorted(self.promos.values(), key=lambda item: item.code)
            if promo.active
        ]

    def disable_promo_code(self, raw_code: str, **kwargs):
        from diet_bot.promo_codes import PromoCodeDefinition, normalize_promo_code

        self.disable_calls.append((raw_code, dict(kwargs)))
        code = normalize_promo_code(raw_code)
        existing = self.promos.get(code)
        if existing is None:
            return None
        definition = existing.to_definition()
        disabled = PromoCodeDefinition(
            code=definition.code,
            kind=definition.kind,
            active=False,
            max_redemptions=definition.max_redemptions,
            per_user_limit=definition.per_user_limit,
            expires_at=definition.expires_at,
            discount_percent=definition.discount_percent,
            discount_amount=definition.discount_amount,
            monthly_duration_months=definition.monthly_duration_months,
        )
        stored = _stored_promo_code(disabled, **kwargs)
        self.promos[disabled.code] = stored
        return stored

    def reserve_promo_code(self, raw_code: str, **kwargs):
        from diet_bot.promo_codes import PromoCodeKind, normalize_promo_code

        self.reserve_calls.append((raw_code, dict(kwargs)))
        if not self.results:
            code = normalize_promo_code(raw_code)
            promo = self.promos.get(code)
            expected_kind = kwargs.get("kind")
            if (
                promo is None
                or not promo.active
                or promo.kind != (expected_kind or PromoCodeKind.MONTHLY_ACCESS)
            ):
                return _promo_store_result("not_found", code=code, chat_id=kwargs["chat_id"])
            return _promo_store_result("reserved", code=code, chat_id=kwargs["chat_id"])
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def finalize_promo_redemption(self, redemption_id: int, **kwargs):
        self.finalize_calls.append((int(redemption_id), dict(kwargs)))
        return types.SimpleNamespace(redemption_id=redemption_id, status="redeemed")

    def release_promo_redemption(self, redemption_id: int, **kwargs):
        self.release_calls.append((int(redemption_id), dict(kwargs)))
        return types.SimpleNamespace(redemption_id=redemption_id, status="released")


def _stored_promo_code(definition, **kwargs):
    definition_copy = type(definition)(**definition.to_dict())
    return types.SimpleNamespace(
        code=definition_copy.code,
        kind=definition_copy.kind,
        active=definition_copy.active,
        max_redemptions=definition_copy.max_redemptions,
        per_user_limit=definition_copy.per_user_limit,
        expires_at=definition_copy.expires_at,
        discount_percent=definition_copy.discount_percent,
        discount_amount=definition_copy.discount_amount,
        monthly_duration_months=definition_copy.monthly_duration_months,
        created_by=kwargs.get("created_by"),
        disabled_by=kwargs.get("disabled_by"),
        metadata=kwargs.get("metadata") or {},
        campaign_key=kwargs.get("campaign_key"),
        to_definition=lambda: definition_copy,
    )


class _PromoEntitlementServiceDouble:
    def __init__(self) -> None:
        self.grants: list[tuple[int, str]] = []
        self.grant_kwargs: list[dict[str, object]] = []

    def apply_subscription_payment(self, chat_id: int, charge_id: str, **kwargs):
        self.grants.append((int(chat_id), charge_id))
        self.grant_kwargs.append(dict(kwargs))
        return types.SimpleNamespace(applied=True, grant="subscription", duplicate=False)


def _install_postgres_promo_store_double(
    monkeypatch: pytest.MonkeyPatch,
    store: _PostgresPromoStoreDouble,
) -> None:
    fake_module = types.ModuleType("diet_bot.postgres_promo_store")

    class FakePostgresPromoStore:
        def __init__(self, database_url: str, **kwargs) -> None:
            store.init_calls.append((database_url, dict(kwargs)))

        def get_promo_code(self, raw_code: str):
            return store.get_promo_code(raw_code)

        def create_or_update_promo_code(self, definition, **kwargs):
            return store.create_or_update_promo_code(definition, **kwargs)

        def list_active_promo_codes(self, **kwargs):
            return store.list_active_promo_codes(**kwargs)

        def disable_promo_code(self, raw_code: str, **kwargs):
            return store.disable_promo_code(raw_code, **kwargs)

        def reserve_promo_code(self, raw_code: str, **kwargs):
            return store.reserve_promo_code(raw_code, **kwargs)

        def finalize_promo_redemption(self, redemption_id: int, **kwargs):
            return store.finalize_promo_redemption(redemption_id, **kwargs)

        def release_promo_redemption(self, redemption_id: int, **kwargs):
            return store.release_promo_redemption(redemption_id, **kwargs)

    fake_module.PostgresPromoStore = FakePostgresPromoStore
    monkeypatch.setitem(sys.modules, "diet_bot.postgres_promo_store", fake_module)


def test_telegram_app_import_does_not_import_postgres_or_psycopg_on_json_path() -> None:
    code = """
import builtins
import os
import sys

os.environ["DIET_BOT_STORAGE_BACKEND"] = "json"
os.environ.pop("DIET_BOT_DATABASE_URL", None)

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name.startswith((
        "diet_bot.postgres_single_poller_guard",
        "diet_bot.postgres_entitlement_store",
        "diet_bot.postgres_weekly_pdf_job_store",
        "diet_bot.postgres_one_day_generation_job_store",
        "diet_bot.postgres_payment_store",
        "diet_bot.postgres_chat_state_store",
        "diet_bot.postgres_chat_state_migrations",
        "psycopg",
    )):
        raise AssertionError(f"telegram_app import touched postgres dependency {name}")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import diet_bot.telegram_app
assert "diet_bot.postgres_single_poller_guard" not in sys.modules
assert "diet_bot.postgres_entitlement_store" not in sys.modules
assert "diet_bot.postgres_weekly_pdf_job_store" not in sys.modules
assert "diet_bot.postgres_one_day_generation_job_store" not in sys.modules
assert "diet_bot.postgres_payment_store" not in sys.modules
assert "diet_bot.postgres_chat_state_store" not in sys.modules
assert "diet_bot.postgres_chat_state_migrations" not in sys.modules
assert "psycopg" not in sys.modules
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(["src", env.get("PYTHONPATH", "")])

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.anyio
async def test_payment_callback_double_click_reuses_pending_order_without_second_invoice(monkeypatch) -> None:
    from dataclasses import replace
    from itertools import count
    from threading import Lock

    import diet_bot.telegram_app as telegram_app
    from diet_bot.payment_service import PaymentService
    from diet_bot.payments import (
        ORDER_STATUS_PENDING,
        PRODUCT_SUBSCRIPTION_MONTH,
        PROVIDER_TELEGRAM_STARS,
        PaymentOrder,
    )

    class PendingRepo:
        def __init__(self) -> None:
            self.orders: dict[str, PaymentOrder] = {}
            self.lock = Lock()

        def create_order(self, order: PaymentOrder) -> PaymentOrder:
            with self.lock:
                self.orders[order.order_id] = order
                return order

        def create_or_reuse_pending_order(self, order: PaymentOrder, **_kwargs) -> PaymentOrder:
            with self.lock:
                for existing in self.orders.values():
                    if (
                        int(existing.chat_id) == int(order.chat_id)
                        and existing.product == order.product
                        and existing.provider == order.provider
                        and int(existing.amount) == int(order.amount)
                        and existing.currency == order.currency
                        and existing.status == ORDER_STATUS_PENDING
                    ):
                        return replace(existing, reused_pending=True)
                self.orders[order.order_id] = order
                return order

        def get_order(self, order_id: str) -> PaymentOrder | None:
            return self.orders.get(order_id)

        def record_event(self, _event):
            raise NotImplementedError

        def record_charge(self, _charge):
            raise NotImplementedError

        def mark_order_paid(self, order_id: str) -> PaymentOrder:
            return self.orders[order_id]

        def mark_order_granted(self, order_id: str) -> PaymentOrder:
            return self.orders[order_id]

        def mark_order_failed(self, order_id: str, reason: str | None = None) -> PaymentOrder:
            failed = replace(self.orders[order_id], status="failed", failure_reason=reason)
            self.orders[order_id] = failed
            return failed

    class FakeBot:
        def __init__(self) -> None:
            self.invoice_links: list[dict[str, object]] = []

        async def create_invoice_link(self, **kwargs) -> str:
            self.invoice_links.append(dict(kwargs))
            return "https://t.me/invoice/test"

    class FakeMessage:
        def __init__(self) -> None:
            self.chat = types.SimpleNamespace(id=202, type="private")
            self.from_user = types.SimpleNamespace(id=777)
            self.bot = FakeBot()
            self.texts: list[str] = []

        async def answer(self, text: str, **_kwargs) -> None:
            self.texts.append(text)

    class FakeCallback:
        def __init__(self, message: FakeMessage) -> None:
            self.data = telegram_app.CALLBACK_PAY_TELEGRAM_STARS
            self.message = message
            self.from_user = types.SimpleNamespace(id=101)
            self.answers: list[str | None] = []

        async def answer(self, text: str | None = None, **_kwargs) -> None:
            self.answers.append(text)

    repo = PendingRepo()
    sequence = count(1)
    service = PaymentService(
        repo,
        order_id_factory=lambda: f"order_{next(sequence):08d}",
        nonce_factory=lambda: f"nonce_{next(sequence):08d}",
    )

    async def no_active_subscription(_message) -> bool:
        return False

    monkeypatch.setattr(telegram_app, "PAYMENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(telegram_app, "Message", FakeMessage)
    monkeypatch.setattr(telegram_app, "_payment_service", lambda: service, raising=False)
    monkeypatch.setattr(telegram_app, "_send_active_subscription_notice_if_needed", no_active_subscription)
    message = FakeMessage()

    await telegram_app.handle_callback(FakeCallback(message))
    await telegram_app.handle_callback(FakeCallback(message))

    expected_notice = (
        "\u0421\u0447\u0435\u0442 \u0443\u0436\u0435 \u0441\u043e\u0437\u0434\u0430\u043d. "
        "\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435 "
        "\u043f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\u0443\u044e "
        "\u0441\u0441\u044b\u043b\u043a\u0443 \u0434\u043b\u044f "
        "\u043e\u043f\u043b\u0430\u0442\u044b \u0438\u043b\u0438 "
        "\u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 "
        "\u043f\u043e\u0437\u0436\u0435."
    )
    assert len(repo.orders) == 1
    assert len(message.bot.invoice_links) == 1
    assert message.texts[-1] == expected_notice
    saved_order = next(iter(repo.orders.values()))
    assert saved_order.product == PRODUCT_SUBSCRIPTION_MONTH
    assert saved_order.provider == PROVIDER_TELEGRAM_STARS


@pytest.mark.anyio
async def test_one_day_generation_delivery_offloads_plan_build_to_thread(monkeypatch) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.domain import (
        ActivityLevel,
        CookingTimePreference,
        Goal,
        Meal,
        MealPlan,
        NutrientVector,
        NutritionTargets,
        SafetyResult,
        Sex,
        UserProfile,
    )
    from diet_bot.one_day_generation_jobs import OneDayGenerationJob, OneDayGenerationRequestSnapshot

    plan = MealPlan(
        (Meal("Breakfast", (), "Recipe", recipe_id="r-thread"),),
        NutritionTargets(
            bmi=22,
            bmi_category="normal",
            bmr_kcal=1500,
            tdee_kcal=2000,
            water_l=2.0,
            targets=NutrientVector({"energy_kcal": 2000}),
            calorie_bounds=(1800, 2200),
            macro_bounds={},
        ),
        SafetyResult(can_generate_plan=True),
    )
    offload_depth = 0
    to_thread_calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        nonlocal offload_depth

        to_thread_calls.append((func, args, dict(kwargs)))
        offload_depth += 1
        try:
            return func(*args, **kwargs)
        finally:
            offload_depth -= 1

    def fake_build_one_day_plan(profile, **kwargs):
        assert offload_depth > 0, "build_one_day_plan must be called through asyncio.to_thread"
        assert profile.age == 44
        assert kwargs["variety_seed"] == 1234
        assert kwargs["avoided_recipe_ids"] == {"old-id"}
        assert kwargs["avoided_recipe_keys"] == {"breakfast:old"}
        assert kwargs["recipe_source"] == "curated_only"
        return plan

    monkeypatch.setattr(telegram_app.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(telegram_app, "build_one_day_plan", fake_build_one_day_plan)

    snapshot = OneDayGenerationRequestSnapshot(
        request_kind="telegram_one_day",
        request_payload={
            "include_default_after_plan_keyboard": False,
            "recent_recipe_keys": ["breakfast:old"],
        },
        profile=telegram_app._profile_to_dict(
            UserProfile(
                age=44,
                sex=Sex.MALE,
                height_cm=178,
                weight_kg=86,
                goal=Goal.LOSE,
                activity=ActivityLevel.MODERATE,
                meal_count=4,
                cooking_time=CookingTimePreference.QUICK,
            )
        ),
        recent_recipe_ids=("old-id",),
        generation_seed="1234",
    )
    job = OneDayGenerationJob(
        job_id=uuid4(),
        chat_id=91_200,
        idempotency_key="telegram_message:91200:1:one_day",
        status="running",
        consumption_source="monthly",
        refund_status="pending",
        delivery_status="not_started",
        expected_value_messages=0,
        delivered_value_messages=0,
        stale_after=datetime(2026, 5, 30, tzinfo=UTC),
        request_snapshot=snapshot,
    )

    delivery = await telegram_app._prepare_one_day_generation_delivery(job, bot=object())

    assert [call[0] for call in to_thread_calls] == [fake_build_one_day_plan]
    assert [value.value_message_key for value in delivery.value_messages] == [
        "meal:00:r-thread",
        "summary:daily_totals",
        "summary:shopping",
    ]


def test_postgres_promo_activation_uses_store_without_json_save(monkeypatch, tmp_path) -> None:
    import diet_bot.telegram_app as telegram_app

    chat_id = 80_301
    promo_path = tmp_path / "promo_codes.json"
    promo_path.write_text('{"codes":{"FB-ABCD-EFGH-2345":{}}}', encoding="utf-8")
    config = _postgres_runtime_config(tmp_path)
    store = _PostgresPromoStoreDouble(_promo_store_result("reserved", chat_id=chat_id))
    service = _PromoEntitlementServiceDouble()

    def fail_json_save(*_args, **_kwargs):
        raise AssertionError("Postgres promo activation must not save JSON promo state")

    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "save_promo_codes", fail_json_save)
    monkeypatch.setattr(telegram_app, "_entitlement_service", lambda: service)
    _install_postgres_promo_store_double(monkeypatch, store)

    activation = telegram_app._activate_promo_code_for_chat(chat_id, "fb abcd efgh 2345")

    assert activation.status == "activated"
    assert activation.code == "FB-ABCD-EFGH-2345"
    assert store.init_calls == [("postgresql://user:secret@example/db", {"connect_timeout": 5})]
    assert store.reserve_calls == [
        (
            "fb abcd efgh 2345",
            {
                "chat_id": chat_id,
                "idempotency_key": "promo:FB-ABCD-EFGH-2345:chat:80301:activation",
                "kind": telegram_app.PromoCodeKind.MONTHLY_ACCESS,
                "entitlement_charge_id": "promo:FB-ABCD-EFGH-2345",
            },
        ),
    ]
    assert store.finalize_calls == [
        (90_001, {"entitlement_charge_id": "promo:FB-ABCD-EFGH-2345"}),
    ]
    assert store.release_calls == []
    assert service.grants == [(chat_id, "promo:FB-ABCD-EFGH-2345")]


@pytest.mark.parametrize(
    ("store_status", "activation_status"),
    [
        ("already_used", "already_used"),
        ("max_uses_reached", "already_used"),
        ("expired", "expired"),
        ("disabled", "disabled"),
        ("not_found", "not_found"),
        ("not_access_code", "not_access_code"),
    ],
)
def test_postgres_promo_activation_maps_store_rejections(
    monkeypatch,
    tmp_path,
    store_status: str,
    activation_status: str,
) -> None:
    import diet_bot.telegram_app as telegram_app

    chat_id = 80_302
    config = _postgres_runtime_config(tmp_path)
    store = _PostgresPromoStoreDouble(_promo_store_result(store_status, chat_id=chat_id))
    service = _PromoEntitlementServiceDouble()

    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "save_promo_codes", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(telegram_app, "_entitlement_service", lambda: service)
    _install_postgres_promo_store_double(monkeypatch, store)

    activation = telegram_app._activate_promo_code_for_chat(chat_id, "FB-ABCD-EFGH-2345")

    assert activation.status == activation_status
    assert service.grants == []
    assert store.finalize_calls == []
    assert store.release_calls == []


def test_postgres_promo_duplicate_activation_does_not_grant_twice(monkeypatch, tmp_path) -> None:
    import diet_bot.telegram_app as telegram_app

    chat_id = 80_303
    config = _postgres_runtime_config(tmp_path)
    store = _PostgresPromoStoreDouble(
        _promo_store_result("reserved", chat_id=chat_id),
        _promo_store_result("already_redeemed", chat_id=chat_id),
    )
    service = _PromoEntitlementServiceDouble()

    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "_entitlement_service", lambda: service)
    _install_postgres_promo_store_double(monkeypatch, store)

    first = telegram_app._activate_promo_code_for_chat(chat_id, "FB-ABCD-EFGH-2345")
    second = telegram_app._activate_promo_code_for_chat(chat_id, "FB-ABCD-EFGH-2345")

    assert first.status == "activated"
    assert second.status == "already_used"
    assert second.used_by_chat_id == chat_id
    assert service.grants == [(chat_id, "promo:FB-ABCD-EFGH-2345")]
    assert store.finalize_calls == [
        (90_001, {"entitlement_charge_id": "promo:FB-ABCD-EFGH-2345"}),
    ]


def test_postgres_promo_activation_ignores_corrupt_json_state(monkeypatch, tmp_path) -> None:
    import diet_bot.telegram_app as telegram_app

    chat_id = 80_304
    promo_path = tmp_path / "promo_codes.json"
    promo_path.write_text("{not valid json", encoding="utf-8")
    config = _postgres_runtime_config(tmp_path)
    store = _PostgresPromoStoreDouble(_promo_store_result("reserved", chat_id=chat_id))
    service = _PromoEntitlementServiceDouble()

    def fail_json_save(*_args, **_kwargs):
        raise AssertionError("Corrupt JSON fallback must not be rewritten on Postgres promo path")

    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "save_promo_codes", fail_json_save)
    monkeypatch.setattr(telegram_app, "_entitlement_service", lambda: service)
    _install_postgres_promo_store_double(monkeypatch, store)

    activation = telegram_app._activate_promo_code_for_chat(chat_id, "FB-ABCD-EFGH-2345")

    assert activation.status == "activated"
    assert service.grants == [(chat_id, "promo:FB-ABCD-EFGH-2345")]
    assert store.reserve_calls
    assert promo_path.read_text(encoding="utf-8") == "{not valid json"


def test_postgres_admin_monthly_code_uses_store_and_can_be_redeemed(
    monkeypatch,
    tmp_path,
) -> None:
    import diet_bot.telegram_app as telegram_app

    admin_user_id = 700
    chat_id = 80_305
    config = _postgres_runtime_config(tmp_path)
    store = _PostgresPromoStoreDouble()
    service = _PromoEntitlementServiceDouble()

    def fail_json_load(*_args, **_kwargs):
        raise AssertionError("Postgres admin monthly creation must not load JSON promo state")

    def fail_json_save(*_args, **_kwargs):
        raise AssertionError("Postgres admin monthly creation must not save JSON promo state")

    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "load_promo_codes", fail_json_load)
    monkeypatch.setattr(telegram_app, "save_promo_codes", fail_json_save)
    monkeypatch.setattr(telegram_app, "generate_promo_codes", lambda *_args, **_kwargs: ["FB-ADMN-MON1-2026"])
    monkeypatch.setattr(telegram_app, "_entitlement_service", lambda: service)
    _install_postgres_promo_store_double(monkeypatch, store)

    promo = telegram_app._create_admin_monthly_access_promo_code(admin_user_id=admin_user_id)
    activation = telegram_app._activate_promo_code_for_chat(chat_id, promo.code)

    assert promo.code == "FB-ADMN-MON1-2026"
    assert promo.kind == telegram_app.PromoCodeKind.MONTHLY_ACCESS
    assert activation.status == "activated"
    assert service.grants == [(chat_id, "promo:FB-ADMN-MON1-2026")]
    assert store.create_calls == [
        (
            promo,
            {
                "created_by": admin_user_id,
                "metadata": {"source": "telegram_admin_menu", "action": "create_monthly_access"},
            },
        ),
    ]
    assert store.reserve_calls == [
        (
            promo.code,
            {
                "chat_id": chat_id,
                "idempotency_key": f"promo:{promo.code}:chat:{chat_id}:activation",
                "kind": telegram_app.PromoCodeKind.MONTHLY_ACCESS,
                "entitlement_charge_id": f"promo:{promo.code}",
            },
        ),
    ]


def test_postgres_admin_discount_create_list_and_disable_use_store_not_json(
    monkeypatch,
    tmp_path,
) -> None:
    import diet_bot.telegram_app as telegram_app

    admin_user_id = 701
    config = _postgres_runtime_config(tmp_path)
    store = _PostgresPromoStoreDouble()

    def fail_json_load(*_args, **_kwargs):
        raise AssertionError("Postgres admin discount flow must not load JSON promo state")

    def fail_json_save(*_args, **_kwargs):
        raise AssertionError("Postgres admin discount flow must not save JSON promo state")

    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "load_promo_codes", fail_json_load)
    monkeypatch.setattr(telegram_app, "save_promo_codes", fail_json_save)
    _install_postgres_promo_store_double(monkeypatch, store)

    parsed = telegram_app._AdminDiscountPromoInput(code="FB-DISC-POST-2026", percent=20)
    promo, create_error = telegram_app._create_or_update_admin_discount_promo(
        parsed,
        admin_user_id=admin_user_id,
    )
    listed = telegram_app._list_admin_discount_promos()
    disabled, disable_error = telegram_app._disable_admin_discount_promo(
        "fb disc post 2026",
        admin_user_id=admin_user_id,
    )

    assert create_error is None
    assert disable_error is None
    assert promo is not None
    assert disabled is not None
    assert promo.code == "FB-DISC-POST-2026"
    assert promo.kind == telegram_app.PromoCodeKind.DISCOUNT
    assert promo.discount_percent == 20
    assert [item.code for item in listed] == ["FB-DISC-POST-2026"]
    assert disabled.active is False
    assert store.create_calls == [
        (
            promo,
            {
                "created_by": admin_user_id,
                "metadata": {"source": "telegram_admin_menu", "action": "create_discount"},
            },
        ),
    ]
    assert store.list_calls == [{}]
    assert store.disable_calls == [
        ("FB-DISC-POST-2026", {"disabled_by": admin_user_id}),
    ]


def test_json_admin_discount_flow_remains_fallback(monkeypatch, tmp_path) -> None:
    from diet_bot.runtime_config import load_runtime_config
    import diet_bot.telegram_app as telegram_app

    promo_path = tmp_path / "promo_codes.json"
    config = load_runtime_config(
        {
            "DIET_BOT_STORAGE_BACKEND": "json",
            "DIET_BOT_PROMO_CODES_STATE_FILE": str(promo_path),
        },
    )

    monkeypatch.setattr(telegram_app, "PROMO_CODES_STATE_FILE", promo_path)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)

    parsed = telegram_app._AdminDiscountPromoInput(code="FB-JSON-FALL-2026", percent=15)
    promo, create_error = telegram_app._create_or_update_admin_discount_promo(
        parsed,
        admin_user_id=702,
    )
    listed = telegram_app._list_admin_discount_promos()
    disabled, disable_error = telegram_app._disable_admin_discount_promo(
        "fb json fall 2026",
        admin_user_id=702,
    )
    loaded = telegram_app.load_promo_codes(promo_path)

    assert create_error is None
    assert disable_error is None
    assert promo is not None
    assert disabled is not None
    assert [item.code for item in listed] == ["FB-JSON-FALL-2026"]
    assert loaded["FB-JSON-FALL-2026"].active is False


def test_chat_state_runtime_json_path_does_not_import_postgres_or_psycopg(tmp_path) -> None:
    code = f"""
import builtins
import sys
from pathlib import Path

from diet_bot.runtime_config import load_runtime_config
from diet_bot.chat_state_runtime import create_chat_state_store, validate_chat_state_store_for_startup

state_path = Path({str(tmp_path / "history.json")!r})
state_path.write_text("{{}}", encoding="utf-8")
config = load_runtime_config({{
    "DIET_BOT_STORAGE_BACKEND": "json",
    "DIET_BOT_STATE_FILE": str(state_path),
}})

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name.startswith((
        "diet_bot.postgres_chat_state_store",
        "diet_bot.postgres_chat_state_migrations",
        "psycopg",
    )):
        raise AssertionError(f"JSON chat state runtime imported postgres dependency {{name}}")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
store = create_chat_state_store(config)
validate_chat_state_store_for_startup(config, store)
assert store.load_all() == {{}}
assert "diet_bot.postgres_chat_state_store" not in sys.modules
assert "diet_bot.postgres_chat_state_migrations" not in sys.modules
assert "psycopg" not in sys.modules
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(["src", env.get("PYTHONPATH", "")])

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_chat_state_runtime_postgres_validates_schema_without_initializing(monkeypatch) -> None:
    from diet_bot.chat_state_runtime import validate_chat_state_store_for_startup
    from diet_bot.runtime_config import load_runtime_config

    calls: list[tuple[str, str]] = []
    config = load_runtime_config(
        {
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        },
    )

    class FakePostgresChatStateStore:
        def __init__(self, database_url: str, **_kwargs) -> None:
            calls.append(("init", database_url))

        def initialize(self) -> None:
            calls.append(("initialize", "called"))

        def validate_schema(self) -> None:
            calls.append(("validate_schema", "called"))

    fake_module = types.ModuleType("diet_bot.postgres_chat_state_store")
    fake_module.PostgresChatStateStore = FakePostgresChatStateStore

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_chat_state_store", fake_module)

    validate_chat_state_store_for_startup(config)

    assert calls == [
        ("init", "postgresql://user:secret@example/db"),
        ("validate_schema", "called"),
    ]


def test_telegram_app_uses_postgres_chat_state_store_when_backend_is_postgres(monkeypatch) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    calls: list[tuple[str, str]] = []
    config = load_runtime_config(
        {
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        },
    )

    class FakePostgresChatStateStore:
        def __init__(self, database_url: str, **_kwargs) -> None:
            calls.append(("init", database_url))

    fake_module = types.ModuleType("diet_bot.postgres_chat_state_store")
    fake_module.PostgresChatStateStore = FakePostgresChatStateStore

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_chat_state_store", fake_module)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "_CHAT_STATE_STORE", None)
    monkeypatch.setattr(telegram_app, "_CHAT_STATE_STORE_KEY", None, raising=False)

    store = telegram_app._chat_state_store()

    assert isinstance(store, FakePostgresChatStateStore)
    assert calls == [("init", "postgresql://user:secret@example/db")]


def test_run_bot_postgres_startup_acquires_guard_even_outside_production(monkeypatch) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    fake_bot = object()
    events: list[str] = []
    polled: list[object] = []
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "123456:test-token",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        },
    )

    class FakeDispatcher:
        async def start_polling(self, bot) -> None:
            polled.append(bot)

    async def fake_set_commands(_bot) -> None:
        return None

    class FakeGuard:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://user:secret@example/db"
            events.append("guard_init")

        def acquire(self) -> FakeGuard:
            events.append("guard_acquire")
            return self

        def close(self) -> None:
            events.append("guard_close")

    def fake_validate_entitlement_storage(startup_config) -> None:
        assert startup_config is config
        events.append("validate_entitlement")

    def fake_validate_weekly_pdf_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_weekly_pdf")

    def fake_validate_one_day_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_one_day")

    def fake_validate_chat_state(startup_config) -> None:
        assert startup_config is config
        events.append("validate_chat_state")

    def fake_bot_factory(_token: str):
        events.append("bot")
        return fake_bot

    fake_guard_module = types.ModuleType("diet_bot.postgres_single_poller_guard")
    fake_guard_module.PostgresSinglePollerGuard = FakeGuard

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_single_poller_guard", fake_guard_module)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "validate_chat_state_store_for_startup", fake_validate_chat_state)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", fake_validate_entitlement_storage)
    monkeypatch.setattr(
        telegram_app,
        "validate_weekly_pdf_job_runtime_for_startup",
        fake_validate_weekly_pdf_jobs,
    )
    monkeypatch.setattr(
        telegram_app,
        "validate_one_day_generation_job_store_for_startup",
        fake_validate_one_day_jobs,
    )
    monkeypatch.setattr(telegram_app, "Bot", fake_bot_factory)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", fake_set_commands)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())

    asyncio.run(telegram_app.run_bot())

    assert polled == [fake_bot]
    assert events == [
        "validate_chat_state",
        "validate_entitlement",
        "validate_weekly_pdf",
        "validate_one_day",
        "guard_init",
        "guard_acquire",
        "bot",
        "guard_close",
    ]


def test_run_bot_payment_enabled_validates_payment_runtime_before_bot(monkeypatch, tmp_path) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    events: list[str] = []
    fake_bot = object()
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "123456:test-token",
            "DIET_BOT_PAYMENTS_ENABLED": "1",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
            "DIET_BOT_PAYMENT_RECOVERY_SPOOL": str(tmp_path / "payments.jsonl"),
        },
    )

    class FakeDispatcher:
        async def start_polling(self, bot) -> None:
            assert bot is fake_bot
            events.append("start_polling")

    async def fake_set_commands(_bot) -> None:
        events.append("set_commands")

    def fake_bot_factory(_token: str):
        events.append("bot")
        return fake_bot

    def fake_validate_entitlement_storage(startup_config) -> None:
        assert startup_config is config
        events.append("validate_entitlement")

    def fake_validate_weekly_pdf_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_weekly_pdf")

    def fake_validate_one_day_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_one_day")

    def fake_validate_chat_state(startup_config) -> None:
        assert startup_config is config
        events.append("validate_chat_state")

    def fake_validate_payment(startup_config) -> None:
        assert startup_config is config
        events.append("validate_payment")

    class FakeGuard:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://user:secret@example/db"
            events.append("guard_init")

        def acquire(self) -> FakeGuard:
            events.append("guard_acquire")
            return self

        def close(self) -> None:
            events.append("guard_close")

    fake_guard_module = types.ModuleType("diet_bot.postgres_single_poller_guard")
    fake_guard_module.PostgresSinglePollerGuard = FakeGuard

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_single_poller_guard", fake_guard_module)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "validate_chat_state_store_for_startup", fake_validate_chat_state)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", fake_validate_entitlement_storage)
    monkeypatch.setattr(
        telegram_app,
        "validate_weekly_pdf_job_runtime_for_startup",
        fake_validate_weekly_pdf_jobs,
    )
    monkeypatch.setattr(
        telegram_app,
        "validate_one_day_generation_job_store_for_startup",
        fake_validate_one_day_jobs,
    )
    monkeypatch.setattr(telegram_app, "validate_payment_runtime_for_startup", fake_validate_payment)
    monkeypatch.setattr(telegram_app, "Bot", fake_bot_factory)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", fake_set_commands)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())

    asyncio.run(telegram_app.run_bot())

    assert events == [
        "validate_chat_state",
        "validate_entitlement",
        "validate_weekly_pdf",
        "validate_one_day",
        "validate_payment",
        "guard_init",
        "guard_acquire",
        "bot",
        "set_commands",
        "start_polling",
        "guard_close",
    ]


def test_run_bot_json_startup_does_not_import_postgres_or_psycopg(monkeypatch, tmp_path) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    subscriptions_path = tmp_path / "subscriptions.json"
    subscriptions_path.write_text("{}", encoding="utf-8")
    fake_bot = object()
    polled: list[object] = []
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "123456:test-token",
            "DIET_BOT_SUBSCRIPTIONS_STATE_FILE": str(subscriptions_path),
        },
    )
    imported: list[str] = []

    class FakeDispatcher:
        async def start_polling(self, bot) -> None:
            polled.append(bot)

    async def fake_set_commands(_bot) -> None:
        return None

    original_import = __import__

    def guarded_import(name, *args, **kwargs):
        imported.append(name)
        if name.startswith((
            "diet_bot.postgres_single_poller_guard",
            "diet_bot.postgres_entitlement_store",
            "diet_bot.postgres_weekly_pdf_job_store",
            "diet_bot.postgres_one_day_generation_job_store",
            "diet_bot.postgres_payment_store",
            "diet_bot.postgres_chat_state_store",
            "diet_bot.postgres_chat_state_migrations",
            "psycopg",
        )):
            raise AssertionError(f"JSON startup touched postgres dependency {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "diet_bot.postgres_single_poller_guard", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_entitlement_store", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_weekly_pdf_job_store", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_one_day_generation_job_store", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_payment_store", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_chat_state_store", raising=False)
    monkeypatch.delitem(sys.modules, "diet_bot.postgres_chat_state_migrations", raising=False)
    monkeypatch.delitem(sys.modules, "psycopg", raising=False)
    monkeypatch.setattr("builtins.__import__", guarded_import)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "Bot", lambda _token: fake_bot)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", fake_set_commands)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())

    asyncio.run(telegram_app.run_bot())

    assert polled == [fake_bot]
    assert "diet_bot.postgres_single_poller_guard" not in imported
    assert "diet_bot.postgres_entitlement_store" not in imported
    assert "diet_bot.postgres_weekly_pdf_job_store" not in imported
    assert "diet_bot.postgres_one_day_generation_job_store" not in imported
    assert "diet_bot.postgres_payment_store" not in imported
    assert "diet_bot.postgres_chat_state_store" not in imported
    assert "diet_bot.postgres_chat_state_migrations" not in imported
    assert "diet_bot.postgres_single_poller_guard" not in sys.modules
    assert "diet_bot.postgres_entitlement_store" not in sys.modules
    assert "diet_bot.postgres_weekly_pdf_job_store" not in sys.modules
    assert "diet_bot.postgres_one_day_generation_job_store" not in sys.modules
    assert "diet_bot.postgres_payment_store" not in sys.modules
    assert "diet_bot.postgres_chat_state_store" not in sys.modules
    assert "diet_bot.postgres_chat_state_migrations" not in sys.modules
    assert "psycopg" not in sys.modules


def test_run_bot_production_postgres_acquires_guard_before_bot_and_releases(
    monkeypatch,
) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    events: list[str] = []
    fake_bot = object()
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "123456:test-token",
            "DIET_BOT_ENV": "production",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
            "DIET_BOT_ONE_DAY_WORKER_ENABLED": "1",
            "DIET_BOT_WEEKLY_PDF_WORKER_ENABLED": "1",
            "DIET_BOT_SUPPORT_CHAT_ID": "1001",
            "DIET_BOT_PRIVACY_POLICY_URL": "https://example.com/privacy",
        },
    )

    class FakeGuard:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://user:secret@example/db"
            events.append("guard_init")

        def acquire(self) -> FakeGuard:
            events.append("guard_acquire")
            return self

        def close(self) -> None:
            events.append("guard_close")

    class FakeDispatcher:
        async def start_polling(self, bot) -> None:
            assert bot is fake_bot
            events.append("start_polling")

    async def fake_set_commands(bot) -> None:
        assert bot is fake_bot
        events.append("set_commands")

    def fake_bot_factory(_token: str):
        events.append("bot")
        return fake_bot

    def fake_validate_entitlement_storage(startup_config) -> None:
        assert startup_config is config
        events.append("validate_entitlement")

    def fake_validate_weekly_pdf_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_weekly_pdf")

    def fake_validate_one_day_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_one_day")

    def fake_validate_chat_state(startup_config) -> None:
        assert startup_config is config
        events.append("validate_chat_state")

    def fake_start_weekly_pdf_worker(startup_config, bot) -> None:
        assert startup_config is config
        assert bot is fake_bot
        events.append("weekly_worker_start")
        return None

    def fake_start_one_day_worker(startup_config, bot) -> None:
        assert startup_config is config
        assert bot is fake_bot
        events.append("one_day_worker_start")
        return None

    fake_guard_module = types.ModuleType("diet_bot.postgres_single_poller_guard")
    fake_guard_module.PostgresSinglePollerGuard = FakeGuard

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_single_poller_guard", fake_guard_module)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "validate_chat_state_store_for_startup", fake_validate_chat_state)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", fake_validate_entitlement_storage)
    monkeypatch.setattr(
        telegram_app,
        "validate_weekly_pdf_job_runtime_for_startup",
        fake_validate_weekly_pdf_jobs,
    )
    monkeypatch.setattr(
        telegram_app,
        "validate_one_day_generation_job_store_for_startup",
        fake_validate_one_day_jobs,
    )
    monkeypatch.setattr(telegram_app, "Bot", fake_bot_factory)
    monkeypatch.setattr(telegram_app, "_set_bot_commands", fake_set_commands)
    monkeypatch.setattr(telegram_app, "create_dispatcher", lambda: FakeDispatcher())
    monkeypatch.setattr(telegram_app, "_start_weekly_pdf_worker_if_configured", fake_start_weekly_pdf_worker)
    monkeypatch.setattr(telegram_app, "_start_one_day_generation_worker_if_configured", fake_start_one_day_worker)

    asyncio.run(telegram_app.run_bot())

    assert events == [
        "validate_chat_state",
        "validate_entitlement",
        "validate_weekly_pdf",
        "validate_one_day",
        "guard_init",
        "guard_acquire",
        "bot",
        "set_commands",
        "weekly_worker_start",
        "one_day_worker_start",
        "start_polling",
        "guard_close",
    ]


def test_run_bot_guard_failure_exits_before_bot_or_telegram_path(monkeypatch) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    events: list[str] = []
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "123456:test-token",
            "DIET_BOT_ENV": "production",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
            "DIET_BOT_ONE_DAY_WORKER_ENABLED": "1",
            "DIET_BOT_WEEKLY_PDF_WORKER_ENABLED": "1",
            "DIET_BOT_SUPPORT_CHAT_ID": "1001",
            "DIET_BOT_PRIVACY_POLICY_URL": "https://example.com/privacy",
        },
    )

    class FailingGuard:
        def __init__(self, _database_url: str) -> None:
            events.append("guard_init")

        def acquire(self) -> FailingGuard:
            events.append("guard_acquire")
            raise RuntimeError("another production poller is already active.")

    def fail_bot(_token: str):
        raise AssertionError("Bot must not be constructed when single-poller guard fails")

    fake_guard_module = types.ModuleType("diet_bot.postgres_single_poller_guard")
    fake_guard_module.PostgresSinglePollerGuard = FailingGuard

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_single_poller_guard", fake_guard_module)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "validate_chat_state_store_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_weekly_pdf_job_runtime_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_one_day_generation_job_store_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "Bot", fail_bot)

    with pytest.raises(RuntimeError, match="another production poller is already active"):
        asyncio.run(telegram_app.run_bot())

    assert events == ["guard_init", "guard_acquire"]


def test_run_bot_unknown_env_postgres_guard_failure_exits_before_bot(monkeypatch) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    events: list[str] = []
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "123456:test-token",
            "DIET_BOT_ENV": "staging",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        },
    )

    class FailingGuard:
        def __init__(self, _database_url: str) -> None:
            events.append("guard_init")

        def acquire(self) -> FailingGuard:
            events.append("guard_acquire")
            raise RuntimeError("single-poller guard unavailable")

    def fail_bot(_token: str):
        raise AssertionError("Bot must not be constructed when Postgres guard fails")

    fake_guard_module = types.ModuleType("diet_bot.postgres_single_poller_guard")
    fake_guard_module.PostgresSinglePollerGuard = FailingGuard

    monkeypatch.setitem(sys.modules, "diet_bot.postgres_single_poller_guard", fake_guard_module)
    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "validate_chat_state_store_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_weekly_pdf_job_runtime_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_one_day_generation_job_store_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "validate_payment_runtime_for_startup", lambda _config: None)
    monkeypatch.setattr(telegram_app, "Bot", fail_bot)

    with pytest.raises(RuntimeError, match="single-poller guard unavailable"):
        asyncio.run(telegram_app.run_bot())

    assert events == ["guard_init", "guard_acquire"]


def test_run_bot_one_day_startup_validation_failure_exits_before_bot(monkeypatch) -> None:
    import diet_bot.telegram_app as telegram_app
    from diet_bot.runtime_config import load_runtime_config

    events: list[str] = []
    config = load_runtime_config(
        {
            "DIET_BOT_TOKEN": "123456:test-token",
            "DIET_BOT_STORAGE_BACKEND": "postgres",
            "DIET_BOT_DATABASE_URL": "postgresql://user:secret@example/db",
        },
    )

    def fake_validate_chat_state(startup_config) -> None:
        assert startup_config is config
        events.append("validate_chat_state")

    def fake_validate_entitlement_storage(startup_config) -> None:
        assert startup_config is config
        events.append("validate_entitlement")

    def fake_validate_weekly_pdf_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_weekly_pdf")

    def fail_validate_one_day_jobs(startup_config) -> None:
        assert startup_config is config
        events.append("validate_one_day")
        raise RuntimeError("one-day generation job schema missing")

    def fail_payment(_config) -> None:
        raise AssertionError("payment validation must not run after one-day startup validation fails")

    def fail_bot(_token: str):
        raise AssertionError("Bot must not be constructed when one-day validation fails")

    monkeypatch.setattr(telegram_app, "load_runtime_config", lambda: config)
    monkeypatch.setattr(telegram_app, "validate_chat_state_store_for_startup", fake_validate_chat_state)
    monkeypatch.setattr(telegram_app, "_validate_entitlement_storage", fake_validate_entitlement_storage)
    monkeypatch.setattr(
        telegram_app,
        "validate_weekly_pdf_job_runtime_for_startup",
        fake_validate_weekly_pdf_jobs,
    )
    monkeypatch.setattr(
        telegram_app,
        "validate_one_day_generation_job_store_for_startup",
        fail_validate_one_day_jobs,
    )
    monkeypatch.setattr(telegram_app, "validate_payment_runtime_for_startup", fail_payment)
    monkeypatch.setattr(telegram_app, "Bot", fail_bot)

    with pytest.raises(RuntimeError, match="one-day generation job schema missing"):
        asyncio.run(telegram_app.run_bot())

    assert events == [
        "validate_chat_state",
        "validate_entitlement",
        "validate_weekly_pdf",
        "validate_one_day",
    ]
