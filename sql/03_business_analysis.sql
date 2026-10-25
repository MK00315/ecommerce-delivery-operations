-- name: overview
SELECT count(*) AS orders, count(*) FILTER (WHERE sla_eligible) AS sla_eligible_orders,
       count(*) FILTER (WHERE is_late) AS late_orders,
       100.0 * count(*) FILTER (WHERE is_late) / count(*) FILTER (WHERE sla_eligible) AS late_pct,
       avg(delivery_days) FILTER (WHERE sla_eligible) AS mean_delivery_days,
       median(delivery_days) FILTER (WHERE sla_eligible) AS median_delivery_days,
       sum(item_value) AS item_value, sum(freight_value) AS freight_value,
       sum(recorded_payment_value) AS recorded_payment_value,
       count(*) FILTER (WHERE missing_items) AS missing_items,
       count(*) FILTER (WHERE missing_payment) AS missing_payments,
       count(*) FILTER (WHERE missing_review) AS missing_reviews,
       count(*) FILTER (WHERE missing_delivered_timestamp) AS delivered_missing_timestamp
FROM gold.orders;

-- name: order_status
SELECT order_status, count(*) AS orders FROM gold.orders GROUP BY 1 ORDER BY 2 DESC;

-- name: monthly_delivery
WITH monthly AS (
    SELECT purchase_month, count(*) AS orders, count(*) FILTER (WHERE sla_eligible) AS eligible_orders,
           count(*) FILTER (WHERE is_late) AS late_orders,
           100.0 * count(*) FILTER (WHERE is_late) / nullif(count(*) FILTER (WHERE sla_eligible), 0) AS late_pct,
           avg(delivery_days) FILTER (WHERE sla_eligible) AS mean_delivery_days,
           sum(item_value) AS item_value
    FROM gold.orders GROUP BY 1
)
SELECT *, orders - lag(orders) OVER (ORDER BY purchase_month) AS change_from_prior_month
FROM monthly ORDER BY purchase_month;

-- name: customer_state
SELECT customer_state, count(*) AS eligible_orders, count(*) FILTER (WHERE is_late) AS late_orders,
       100.0 * count(*) FILTER (WHERE is_late) / count(*) AS late_pct,
       median(delivery_days) AS median_delivery_days, sum(item_value) AS item_value
FROM gold.sla_orders GROUP BY 1 ORDER BY eligible_orders DESC;

-- name: distance_bands
SELECT CASE WHEN max_distance_km IS NULL THEN 'Unknown'
            WHEN max_distance_km < 100 THEN '0-100 km'
            WHEN max_distance_km < 500 THEN '100-500 km'
            WHEN max_distance_km < 1000 THEN '500-1000 km'
            ELSE '1000+ km' END AS distance_band,
       count(*) AS eligible_orders, count(*) FILTER (WHERE is_late) AS late_orders,
       100.0 * count(*) FILTER (WHERE is_late) / count(*) AS late_pct,
       median(delivery_days) AS median_delivery_days
FROM gold.sla_orders GROUP BY 1 ORDER BY median(max_distance_km) NULLS LAST;

-- name: seller_watchlist
WITH seller AS (
    SELECT seller_id, min(seller_state) AS seller_state,
           count(*) FILTER (WHERE sla_eligible) AS eligible_orders,
           count(*) FILTER (WHERE order_is_late) AS orders_with_late_outcome,
           sum(item_value) AS item_value
    FROM gold.order_sellers GROUP BY 1
)
SELECT *, 100.0 * orders_with_late_outcome / eligible_orders AS late_order_pct,
       dense_rank() OVER (ORDER BY 1.0 * orders_with_late_outcome / eligible_orders DESC) AS rate_rank
FROM seller WHERE eligible_orders >= 50 ORDER BY rate_rank, eligible_orders DESC;

-- name: product_categories
SELECT i.category, count(*) AS item_lines, count(DISTINCT i.order_id) AS orders,
       count(*) FILTER (WHERE o.sla_eligible) AS eligible_item_lines,
       count(*) FILTER (WHERE o.is_late) AS item_lines_on_late_orders,
       100.0 * count(*) FILTER (WHERE o.is_late) / nullif(count(*) FILTER (WHERE o.sla_eligible), 0) AS late_item_pct,
       sum(i.item_value) AS item_value
FROM gold.order_items i JOIN gold.orders o USING (order_id)
GROUP BY 1 ORDER BY item_lines DESC;

-- name: basket_complexity
SELECT multi_seller, count(*) AS eligible_orders, count(*) FILTER (WHERE is_late) AS late_orders,
       100.0 * count(*) FILTER (WHERE is_late) / count(*) AS late_pct,
       median(delivery_days) AS median_delivery_days
FROM gold.sla_orders GROUP BY 1;

-- name: review_association
SELECT is_late, count(*) AS eligible_orders,
       count(latest_review_score) AS reviewed_orders,
       avg(latest_review_score) AS mean_latest_score,
       count(*) FILTER (WHERE latest_review_score <= 2) AS low_review_orders,
       100.0 * count(*) FILTER (WHERE latest_review_score <= 2) / nullif(count(latest_review_score), 0) AS low_review_pct
FROM gold.sla_orders GROUP BY 1 ORDER BY is_late;

-- name: stage_durations
SELECT count(*) AS eligible_orders, count(approval_days) AS approval_observations,
       count(seller_handling_days) AS handling_observations,
       count(carrier_transit_days) AS transit_observations,
       median(approval_days) AS median_approval_days,
       median(seller_handling_days) AS median_handling_days,
       median(carrier_transit_days) AS median_transit_days,
       count(*) FILTER (WHERE invalid_stage_sequence) AS anomalous_stage_orders
FROM gold.sla_orders;

-- name: promised_windows
SELECT CASE WHEN promised_calendar_days < 7 THEN 'Under 7 days'
            WHEN promised_calendar_days < 14 THEN '7-13 days'
            WHEN promised_calendar_days < 21 THEN '14-20 days'
            ELSE '21+ days' END AS promised_window,
       count(*) AS eligible_orders, count(*) FILTER (WHERE is_late) AS late_orders,
       100.0 * count(*) FILTER (WHERE is_late) / count(*) AS late_pct
FROM gold.sla_orders GROUP BY 1 ORDER BY min(promised_calendar_days);

-- name: timestamp_definition_comparison
SELECT count(*) AS eligible_orders, count(*) FILTER (WHERE delivered_at > promised_at) AS late_by_timestamp,
       count(*) FILTER (WHERE is_late) AS late_by_promised_date,
       count(*) FILTER (WHERE delivered_at > promised_at AND NOT is_late) AS same_promised_date_deliveries
FROM gold.sla_orders;
