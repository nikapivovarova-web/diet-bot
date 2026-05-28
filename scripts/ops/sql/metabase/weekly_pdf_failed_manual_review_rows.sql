-- Weekly PDF failed or unresolved manual-review rows with hashed chat identifiers.
SELECT
    job_id,
    md5('chat:' || chat_id::text) AS chat_id_hash,
    status,
    delivery_status,
    refund_status,
    consumption_source,
    requires_manual_review,
    manual_review_reason,
    manual_reviewed_at,
    manual_review_resolution,
    failure_reason,
    finalization_error,
    created_at,
    updated_at,
    started_at,
    heartbeat_at,
    stale_after,
    finished_at
FROM weekly_pdf_jobs
WHERE status = 'failed'
   OR (requires_manual_review IS TRUE AND manual_reviewed_at IS NULL)
   OR delivery_status = 'unknown'
ORDER BY COALESCE(finished_at, updated_at, created_at) DESC;
