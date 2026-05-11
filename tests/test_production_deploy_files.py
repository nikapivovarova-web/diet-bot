from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dockerignore_keeps_secrets_state_and_dumps_out_of_context() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert dockerignore[0] == "*"
    for pattern in (
        "!pyproject.toml",
        "!requirements.lock",
        "!src/**",
        ".env",
        ".env.*",
        ".diet_bot_state/",
        "tmp/",
        "backups/",
        "*.dump",
        "*.sql",
        "*.sql.gz",
    ):
        assert pattern in dockerignore


def test_dockerfile_uses_runtime_lock_and_non_root_user() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY requirements.lock ./" in dockerfile
    assert "pip install --no-cache-dir -r requirements.lock" in dockerfile
    assert "pip install --no-cache-dir --no-deps ." in dockerfile
    assert "COPY . ." not in dockerfile
    assert "USER app:app" in dockerfile


def test_compose_has_local_liveness_logging_limits_and_graceful_stop() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "--polling-liveness" in compose
    assert "max-size: \"10m\"" in compose
    assert "max-file: \"5\"" in compose
    assert "init: true" in compose
    assert "stop_grace_period: 45s" in compose
