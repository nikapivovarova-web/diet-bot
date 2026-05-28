-- Applied application schema migrations by component and version.
SELECT
    CASE
        WHEN version IN ('202605220001', '202605220002') THEN 'entitlements'
        WHEN version = '202605220003' THEN 'payment_ledger'
        WHEN version IN ('202605230001', '202605250001', '202605250002', '202605260001', '202605280001', '202605280002') THEN 'weekly_pdf_jobs'
        WHEN version IN ('202605260002', '202605270001', '202605280003') THEN 'one_day_generation_jobs'
        ELSE 'other'
    END AS component,
    version,
    description,
    applied_at
FROM schema_migrations
ORDER BY applied_at DESC, version DESC;
