-- Payment rows that need operator attention before payment launch expansion.
WITH order_candidates AS (
    SELECT
        order_id,
        md5('chat:' || chat_id::text) AS chat_id_hash,
        product,
        provider,
        amount,
        currency,
        status,
        created_at,
        updated_at,
        paid_at,
        granted_at,
        failed_at,
        CASE
            WHEN status = 'paid' AND granted_at IS NULL THEN 'paid_not_granted'
            WHEN status = 'pending' AND created_at < now() - interval '15 minutes' THEN 'old_pending_order'
            WHEN status = 'failed' THEN 'failed_order'
            ELSE 'not_candidate'
        END AS recovery_candidate_reason
    FROM payment_orders
)
SELECT
    recovery_candidate_reason,
    order_id,
    chat_id_hash,
    product,
    provider,
    amount,
    currency,
    status,
    created_at,
    updated_at,
    paid_at,
    granted_at,
    failed_at
FROM order_candidates
WHERE recovery_candidate_reason <> 'not_candidate'
UNION ALL
SELECT
    'charge_recorded_order_not_granted' AS recovery_candidate_reason,
    payment_orders.order_id,
    md5('chat:' || payment_orders.chat_id::text) AS chat_id_hash,
    payment_orders.product,
    payment_charges.provider,
    payment_charges.amount,
    payment_charges.currency,
    payment_orders.status,
    payment_charges.created_at,
    payment_orders.updated_at,
    payment_orders.paid_at,
    payment_orders.granted_at,
    payment_orders.failed_at
FROM payment_charges
JOIN payment_orders ON payment_orders.order_id = payment_charges.order_id
WHERE payment_charges.status = 'succeeded'
  AND payment_orders.status <> 'granted'
UNION ALL
SELECT
    'successful_payment_orphan_event' AS recovery_candidate_reason,
    event_id AS order_id,
    NULL AS chat_id_hash,
    NULL AS product,
    provider,
    NULL AS amount,
    NULL AS currency,
    event_type AS status,
    created_at,
    created_at AS updated_at,
    NULL AS paid_at,
    NULL AS granted_at,
    NULL AS failed_at
FROM payment_events
WHERE event_type = 'successful_payment_orphan'
ORDER BY created_at DESC;
