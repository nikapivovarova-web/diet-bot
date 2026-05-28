-- Active jobs older than the dashboard threshold.
-- Edit threshold_minutes in Metabase if the runtime alert thresholds change.
WITH threshold AS (
    SELECT interval '30 minutes' AS max_active_age
),
active_jobs AS (
    SELECT
        'one_day' AS job_family,
        job_id,
        md5('chat:' || chat_id::text) AS chat_id_hash,
        status,
        created_at,
        updated_at,
        started_at,
        heartbeat_at,
        stale_after
    FROM one_day_generation_jobs
    WHERE status IN ('queued', 'running')
    UNION ALL
    SELECT
        'weekly_pdf' AS job_family,
        job_id,
        md5('chat:' || chat_id::text) AS chat_id_hash,
        status,
        created_at,
        updated_at,
        started_at,
        heartbeat_at,
        stale_after
    FROM weekly_pdf_jobs
    WHERE status IN ('queued', 'running')
)
SELECT
    job_family,
    job_id,
    chat_id_hash,
    status,
    created_at,
    updated_at,
    started_at,
    heartbeat_at,
    stale_after,
    EXTRACT(EPOCH FROM (now() - created_at))::bigint AS active_age_seconds,
    stale_after < now() AS stale_by_deadline
FROM active_jobs, threshold
WHERE now() - created_at > threshold.max_active_age
   OR stale_after < now()
ORDER BY active_age_seconds DESC;
