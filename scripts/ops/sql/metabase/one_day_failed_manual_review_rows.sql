-- One-day failed or manual-review rows with hashed chat identifiers.
SELECT
    job_id,
    md5('chat:' || chat_id::text) AS chat_id_hash,
    status,
    delivery_status,
    refund_status,
    consumption_source,
    expected_value_messages,
    delivered_value_messages,
    requires_manual_review,
    failure_reason,
    finalization_error,
    created_at,
    updated_at,
    started_at,
    heartbeat_at,
    stale_after,
    finished_at
FROM one_day_generation_jobs
WHERE status = 'failed'
   OR requires_manual_review IS TRUE
   OR delivery_status IN ('partial', 'unknown')
ORDER BY COALESCE(finished_at, updated_at, created_at) DESC;
