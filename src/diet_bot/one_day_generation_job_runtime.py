from __future__ import annotations


def validate_one_day_generation_job_store_for_startup(config: object) -> None:
    if getattr(config, "storage_backend", "json") != "postgres":
        return

    store = _create_postgres_one_day_generation_job_store(config)
    try:
        store.validate_schema()
    except Exception as exc:
        raise RuntimeError(
            "Postgres one-day generation job storage is not ready; "
            "run one-day generation job migrations before startup.",
        ) from exc


def _create_postgres_one_day_generation_job_store(config: object):
    database_url = getattr(config, "database_url", None)
    if not database_url:
        raise RuntimeError("DIET_BOT_DATABASE_URL is required for one-day generation Postgres jobs.")

    from .postgres_one_day_generation_job_store import PostgresOneDayGenerationJobStore

    return PostgresOneDayGenerationJobStore(str(database_url))
