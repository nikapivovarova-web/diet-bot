from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor

from diet_bot import telegram_app
from diet_bot.analytics import AnalyticsConfig, pseudonymous_identifier, sanitize_properties, track_event


class FakeStore:
    def __init__(self) -> None:
        self.events: list[tuple[int | None, str, dict[str, object]]] = []

    def record_analytics_event(
        self,
        user_id: int | None,
        event_name: str,
        properties: dict[str, object],
    ) -> None:
        self.events.append((user_id, event_name, properties))


def test_sanitize_properties_drops_sensitive_fields() -> None:
    properties = sanitize_properties(
        {
            "product": "subscription_month",
            "raw_payload": {"email": "person@example.com"},
            "message_text": "private support request",
            "nested": {
                "source": "callback",
                "email": "person@example.com",
            },
        }
    )

    assert properties == {
        "product": "subscription_month",
        "nested": {"source": "callback"},
    }


def test_disabled_analytics_does_not_touch_store_or_posthog(monkeypatch) -> None:
    class FailingStore:
        def record_analytics_event(self, *args, **kwargs) -> None:
            raise AssertionError("disabled analytics should not touch the store")

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("disabled analytics should not call PostHog")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)

    track_event(
        123,
        "bot_started",
        {"source": "command"},
        store=FailingStore(),
        config=AnalyticsConfig(enabled=False, posthog_api_key="key"),
    )


def test_enabled_analytics_stores_event_and_sends_posthog(monkeypatch) -> None:
    store = FakeStore()
    sent_payloads: list[dict[str, object]] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b"{}"

    def fake_urlopen(request, timeout):
        sent_payloads.append(json.loads(request.data.decode("utf-8")))
        assert timeout == 2.0
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    track_event(
        123,
        "checkout_started",
        {"product": "subscription_month", "token": "secret"},
        store=store,
        config=AnalyticsConfig(enabled=True, posthog_api_key="ph-key"),
    )

    assert store.events == [
        (123, "checkout_started", {"product": "subscription_month"}),
    ]
    assert sent_payloads == [
        {
            "api_key": "ph-key",
            "event": "checkout_started",
            "distinct_id": pseudonymous_identifier(123, prefix="tg"),
            "properties": {"product": "subscription_month"},
        }
    ]
    assert sent_payloads[0]["distinct_id"] != "123"


def test_analytics_drops_forbidden_pii_properties() -> None:
    properties = sanitize_properties(
        {
            "source": "payment",
            "user_id": 123,
            "telegram_id": 456,
            "order_id": "order-secret",
            "username": "client",
            "first_name": "Client",
            "charge_id": "charge-secret",
        }
    )

    assert properties == {"source": "payment"}


def test_posthog_failure_is_swallowed_and_logged(monkeypatch, caplog) -> None:
    store = FakeStore()

    def fake_urlopen(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    track_event(
        123,
        "invoice_created",
        {"provider": "yookassa"},
        store=store,
        config=AnalyticsConfig(enabled=True, posthog_api_key="ph-key"),
    )

    assert store.events == [(123, "invoice_created", {"provider": "yookassa"})]
    assert "Could not send analytics event to PostHog." in caplog.text


def test_production_invalid_posthog_host_is_disabled(monkeypatch) -> None:
    monkeypatch.setenv("DIET_BOT_ENV", "production")
    monkeypatch.setenv("DIET_BOT_ANALYTICS_ENABLED", "1")
    monkeypatch.setenv("POSTHOG_API_KEY", "ph-key")
    monkeypatch.setenv("POSTHOG_HOST", "http://localhost:8000")

    config = AnalyticsConfig.from_env()

    assert config.enabled is True
    assert config.posthog_api_key == ""


def test_posthog_executor_does_not_block_storage_executor(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b"{}"

    def slow_urlopen(*args, **kwargs):
        time.sleep(0.5)
        return FakeResponse()

    monkeypatch.setenv("DIET_BOT_ENV", "development")
    monkeypatch.setenv("DIET_BOT_ANALYTICS_ENABLED", "1")
    monkeypatch.setenv("POSTHOG_API_KEY", "ph-key")
    monkeypatch.setenv("POSTHOG_HOST", "https://app.posthog.com")
    monkeypatch.setattr("urllib.request.urlopen", slow_urlopen)
    monkeypatch.setattr(telegram_app, "_postgres_store", lambda: FakeStore())

    posthog_executor = ThreadPoolExecutor(max_workers=4)
    monkeypatch.setattr(telegram_app, "POSTHOG_EXECUTOR", posthog_executor)
    try:
        asyncio.run(_assert_posthog_does_not_starve_storage_io())
    finally:
        posthog_executor.shutdown(wait=True)


async def _assert_posthog_does_not_starve_storage_io() -> None:
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=4))
    tasks = [
        asyncio.create_task(telegram_app._track_event_async(1000 + index, "checkout_started", {"source": "test"}))
        for index in range(10)
    ]
    await asyncio.sleep(0.05)

    start = time.perf_counter()
    result = await telegram_app._run_storage_io(lambda: "storage-ok")
    elapsed = time.perf_counter() - start

    assert result == "storage-ok"
    assert elapsed < 0.2
    await asyncio.gather(*tasks)
