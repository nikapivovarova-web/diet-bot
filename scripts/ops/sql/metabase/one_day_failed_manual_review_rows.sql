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
    manual_reviewed_at,
    manual_reviewed_by,
    manual_review_resolution,
    manual_review_note,
    failure_reason,
    finalization_error,
    created_at,
    updated_at,
    started_at,
    heartbeat_at,
    stale_after,
    finished_at
FROM one_day_generation_jobs
WHERE (status = 'failed' AND (requires_manual_review IS NOT TRUE OR manual_reviewed_at IS NULL))
   OR (requires_manual_review IS TRUE AND manual_reviewed_at IS NULL)
   OR (delivery_status IN ('partial', 'unknown') AND manual_reviewed_at IS NULL)
ORDER BY COALESCE(finished_at, updated_at, created_at) DESC;
