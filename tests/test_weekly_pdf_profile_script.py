from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.dev import weekly_pdf_profile


def test_weekly_pdf_profile_rejects_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIET_BOT_DATABASE_URL", "postgresql://example.invalid/prod")
    monkeypatch.delenv("TELEGRAM_PROVIDER_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="DIET_BOT_DATABASE_URL"):
        weekly_pdf_profile.assert_safe_local_environment()


def test_weekly_pdf_profile_rejects_provider_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DIET_BOT_DATABASE_URL", raising=False)
    monkeypatch.setenv("TELEGRAM_PROVIDER_TOKEN", "live-token")

    with pytest.raises(RuntimeError, match="TELEGRAM_PROVIDER_TOKEN"):
        weekly_pdf_profile.assert_safe_local_environment()


def test_weekly_pdf_profile_measures_temp_pdf_read_and_delete(tmp_path: Path) -> None:
    created_pdf = tmp_path / "week.pdf"

    def fake_build_week_plan_pdf(_plans, _plan_dates, output_dir=None):
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        created_pdf.write_bytes(b"%PDF-1.4\n%profile smoke\n%%EOF\n")
        return created_pdf

    metrics = weekly_pdf_profile.measure_pdf_payload(
        plans=("plan",),
        plan_dates=(date(2026, 5, 21),),
        output_dir=tmp_path,
        keep_pdf=False,
        count_pages=False,
        build_week_plan_pdf_func=fake_build_week_plan_pdf,
    )

    assert metrics.pdf_bytes == len(b"%PDF-1.4\n%profile smoke\n%%EOF\n")
    assert metrics.page_count is None
    assert metrics.render_seconds >= 0
    assert metrics.read_seconds >= 0
    assert metrics.delete_seconds >= 0
    assert not created_pdf.exists()


def test_weekly_pdf_profile_tracks_current_fixed_box_image_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import diet_bot.pdf_renderer as pdf_renderer

    image_path = tmp_path / "meal.jpg"

    def fake_fixed_box_image_source(path: Path) -> str:
        return f"fixed:{Path(path).name}"

    monkeypatch.setattr(pdf_renderer, "_fixed_box_image_source", fake_fixed_box_image_source)

    with weekly_pdf_profile.track_pdf_assets() as tracker:
        assert pdf_renderer._fixed_box_image_source(image_path) == "fixed:meal.jpg"

    summary = tracker.summary()
    assert summary.image_source_count == 1
    assert str(image_path) in summary.image_sources
