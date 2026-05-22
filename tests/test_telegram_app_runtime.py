from __future__ import annotations

import os
import subprocess
import sys


def test_telegram_app_import_does_not_import_postgres_or_psycopg_on_json_path() -> None:
    code = """
import builtins
import os
import sys

os.environ["DIET_BOT_STORAGE_BACKEND"] = "json"
os.environ.pop("DIET_BOT_DATABASE_URL", None)

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name.startswith(("diet_bot.postgres_entitlement_store", "psycopg")):
        raise AssertionError(f"telegram_app import touched postgres dependency {name}")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import diet_bot.telegram_app
assert "diet_bot.postgres_entitlement_store" not in sys.modules
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
