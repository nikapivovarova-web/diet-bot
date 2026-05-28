-- Weekly PDF queue depth by durable job status.
SELECT
    status,
    count(*) AS jobs,
    count(*) FILTER (WHERE stale_after < now() AND status IN ('queued', 'running')) AS stale_jobs,
    min(created_at) AS oldest_created_at,
    max(updated_at) AS newest_updated_at
FROM weekly_pdf_jobs
GROUP BY status
ORDER BY
    CASE status
        WHEN 'queued' THEN 1
        WHEN 'running' THEN 2
        WHEN 'failed' THEN 3
        WHEN 'cancelled' THEN 4
        WHEN 'succeeded' THEN 5
        ELSE 99
    END;
