from __future__ import annotations

import importlib
import inspect


def test_storage_contract_exposes_paid_production_methods() -> None:
    storage = importlib.import_module("diet_bot.storage")

    assert hasattr(storage, "UserIdentity")
    assert hasattr(storage, "SupportState")
    assert hasattr(storage, "RecipeHistoryItem")
    assert hasattr(storage, "DietBotStore")

    required_methods = {
        "initialize",
        "healthcheck",
        "remember_user",
        "load_chat_state",
        "save_chat_state",
        "load_profile_data",
        "save_profile_data",
        "get_entitlement",
        "save_entitlement",
        "consume_generation_attempt",
        "heartbeat_generation_attempt",
        "start_generation_delivery",
        "complete_generation_attempt",
        "refund_generation_attempt",
        "record_recipe_history",
        "load_recent_recipe_history",
        "cleanup_stale_generations",
        "upsert_promo_code",
        "create_promo_code",
        "get_promo_code",
        "redeem_promo_code",
        "activate_promo_code",
        "create_or_reuse_pending_payment_order",
        "load_payment_order",
        "record_payment_order_pre_checkout_approved",
        "apply_successful_payment",
        "record_support_state",
        "load_support_state",
    }
    actual_methods = {
        name
        for name, value in storage.DietBotStore.__dict__.items()
        if callable(value) and not name.startswith("_")
    }

    assert required_methods <= actual_methods

    complete_signature = inspect.signature(storage.DietBotStore.complete_generation_attempt)
    assert "pdf_path" in complete_signature.parameters
    assert "telegram_message_id" in complete_signature.parameters

    refund_signature = inspect.signature(storage.DietBotStore.refund_generation_attempt)
    assert "error_message" in refund_signature.parameters

    recipe_history_fields = set(storage.RecipeHistoryItem.__dataclass_fields__)
    assert {
        "recipe_id",
        "recipe_key",
        "meal_slot",
        "ration_kind",
        "user_id",
        "generation_id",
        "generated_at",
    } <= recipe_history_fields

    record_history_signature = inspect.signature(storage.DietBotStore.record_recipe_history)
    assert "user_id" in record_history_signature.parameters
    assert "entries" in record_history_signature.parameters

    load_history_signature = inspect.signature(storage.DietBotStore.load_recent_recipe_history)
    assert "user_id" in load_history_signature.parameters
    assert "since" in load_history_signature.parameters
    assert "limit" in load_history_signature.parameters

    pre_checkout_signature = inspect.signature(
        storage.DietBotStore.record_payment_order_pre_checkout_approved
    )
    assert "approved_at" in pre_checkout_signature.parameters

    success_signature = inspect.signature(storage.DietBotStore.apply_successful_payment)
    assert "successful_payment" in success_signature.parameters

    create_order_signature = inspect.signature(
        storage.DietBotStore.create_or_reuse_pending_payment_order
    )
    assert "promo_code" in create_order_signature.parameters
    assert "now" in success_signature.parameters
