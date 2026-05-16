from __future__ import annotations

from diet_bot.postgres_store import _consumption_from_event, _ledger_source_for_consumption
from diet_bot.subscriptions import AttemptConsumption


def test_monthly_consumption_ledger_source_is_ration_specific() -> None:
    assert (
        _ledger_source_for_consumption(AttemptConsumption(True, "one_day", "monthly"))
        == "monthly_one_day"
    )
    assert (
        _ledger_source_for_consumption(AttemptConsumption(True, "weekly_pdf", "monthly"))
        == "monthly_weekly_pdf"
    )


def test_ration_specific_monthly_ledger_source_round_trips_to_domain_source() -> None:
    one_day = _consumption_from_event(
        {
            "source": "monthly_one_day",
            "metadata_json": {"ration_kind": "one_day", "attempt_source": "monthly"},
        }
    )
    weekly_pdf = _consumption_from_event(
        {
            "source": "monthly_weekly_pdf",
            "metadata_json": {"ration_kind": "weekly_pdf", "attempt_source": "monthly"},
        }
    )

    assert one_day == AttemptConsumption(True, "one_day", "monthly")
    assert weekly_pdf == AttemptConsumption(True, "weekly_pdf", "monthly")
