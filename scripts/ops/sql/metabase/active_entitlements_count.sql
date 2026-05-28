-- Active entitlement inventory for the FoodBalance Metabase ops dashboard.
-- Chat identifiers are intentionally not selected.
SELECT
    count(*) AS total_entitlements,
    count(*) FILTER (
        WHERE monthly_one_day_remaining > 0
           OR monthly_weekly_pdf_remaining > 0
           OR extra_one_day_remaining > 0
           OR extra_weekly_pdf_remaining > 0
           OR (
                NULLIF(subscription_period_end, '') IS NOT NULL
                AND NULLIF(subscription_period_end, '')::timestamptz > now()
           )
           OR (
                test_access_enabled IS TRUE
                AND NULLIF(test_access_until, '') IS NOT NULL
                AND NULLIF(test_access_until, '')::timestamptz > now()
           )
    ) AS active_entitlements,
    count(*) FILTER (WHERE monthly_one_day_remaining > 0 OR extra_one_day_remaining > 0) AS one_day_available,
    count(*) FILTER (WHERE monthly_weekly_pdf_remaining > 0 OR extra_weekly_pdf_remaining > 0) AS weekly_pdf_available
FROM entitlements;
