-- Daily paid grant volume by product/provider.
SELECT
    date_trunc('day', COALESCE(granted_at, paid_at, created_at))::date AS day,
    product,
    provider,
    currency,
    status,
    count(*) AS orders,
    sum(amount) AS total_amount
FROM payment_orders
WHERE status IN ('paid', 'granted')
GROUP BY 1, product, provider, currency, status
ORDER BY day DESC, product, provider, status;
