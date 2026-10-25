-- Item-grain fact. Dimension keys are validated before joins by the driver.
CREATE OR REPLACE TABLE gold.order_items AS
SELECT i.*, p.category, p.weight_g,
       p.length_cm * p.height_cm * p.width_cm AS volume_cm3,
       s.state AS seller_state, c.state AS customer_state,
       great_circle_km(s.latitude, s.longitude, c.latitude, c.longitude) AS approximate_distance_km
FROM silver.items i
LEFT JOIN silver.products p USING (product_id)
LEFT JOIN silver.sellers s USING (seller_id)
LEFT JOIN silver.orders o USING (order_id)
LEFT JOIN silver.customers c USING (customer_id);

-- Aggregate every one-to-many source independently BEFORE joining orders.
CREATE OR REPLACE TABLE gold.orders AS
WITH item_totals AS (
    SELECT order_id, count(*) AS item_count, count(DISTINCT seller_id) AS seller_count,
           count(DISTINCT product_id) AS product_count, sum(item_value) AS item_value,
           sum(freight_value) AS freight_value, sum(weight_g) AS known_weight_g,
           count(weight_g) AS items_with_weight, max(approximate_distance_km) AS max_distance_km,
           avg(approximate_distance_km) AS mean_distance_km,
           count(approximate_distance_km) AS items_with_distance
    FROM gold.order_items GROUP BY order_id
), payment_totals AS (
    SELECT order_id, count(*) AS payment_count, sum(payment_value) AS recorded_payment_value,
           count(DISTINCT payment_type) AS payment_type_count,
           max(installments) AS max_installments
    FROM silver.payments GROUP BY order_id
), joined AS (
    SELECT o.*, c.customer_unique_id, c.state AS customer_state,
           c.postcode_prefix AS customer_postcode,
           coalesce(i.item_count, 0) AS item_count, coalesce(i.seller_count, 0) AS seller_count,
           coalesce(i.product_count, 0) AS product_count, i.item_value, i.freight_value,
           i.known_weight_g, i.items_with_weight, i.max_distance_km, i.mean_distance_km,
           i.items_with_distance, coalesce(p.payment_count, 0) AS payment_count,
           p.recorded_payment_value, p.payment_type_count, p.max_installments,
           r.review_score AS latest_review_score, r.answered_at AS latest_review_answered_at,
           coalesce(r.review_count, 0) AS review_count,
           o.order_status = 'delivered' AND o.delivered_at IS NOT NULL
             AND o.purchased_at IS NOT NULL AND o.promised_at IS NOT NULL
             AND o.delivered_at >= o.purchased_at
             AND CAST(o.promised_at AS DATE) >= CAST(o.purchased_at AS DATE) AS sla_eligible
    FROM silver.orders o
    LEFT JOIN silver.customers c USING (customer_id)
    LEFT JOIN item_totals i USING (order_id)
    LEFT JOIN payment_totals p USING (order_id)
    LEFT JOIN silver.latest_reviews r USING (order_id)
)
SELECT *, CAST(purchased_at AS DATE) AS purchase_date,
       CAST(date_trunc('month', purchased_at) AS DATE) AS purchase_month,
       CASE WHEN sla_eligible THEN sla_late(promised_at, delivered_at) END AS is_late,
       CASE WHEN sla_eligible THEN greatest(0, date_diff('day', promised_at::DATE, delivered_at::DATE)) END AS late_calendar_days,
       CASE WHEN delivered_at >= purchased_at THEN epoch(delivered_at - purchased_at) / 86400.0 END AS delivery_days,
       CASE WHEN approved_at >= purchased_at THEN epoch(approved_at - purchased_at) / 86400.0 END AS approval_days,
       CASE WHEN carrier_at >= approved_at THEN epoch(carrier_at - approved_at) / 86400.0 END AS seller_handling_days,
       CASE WHEN delivered_at >= carrier_at THEN epoch(delivered_at - carrier_at) / 86400.0 END AS carrier_transit_days,
       date_diff('day', purchased_at::DATE, promised_at::DATE) AS promised_calendar_days,
       seller_count > 1 AS multi_seller,
       item_count = 0 AS missing_items,
       payment_count = 0 AS missing_payment,
       review_count = 0 AS missing_review,
       order_status = 'delivered' AND delivered_at IS NULL AS missing_delivered_timestamp,
       coalesce(carrier_at < approved_at, false) OR coalesce(delivered_at < carrier_at, false) AS invalid_stage_sequence
FROM joined;

CREATE OR REPLACE TABLE gold.order_sellers AS
SELECT i.order_id, i.seller_id, min(i.seller_state) AS seller_state,
       count(*) AS item_count, sum(i.item_value) AS item_value,
       sum(i.freight_value) AS freight_value, max(i.approximate_distance_km) AS distance_km,
       bool_or(o.sla_eligible) AS sla_eligible, bool_or(o.is_late) AS order_is_late
FROM gold.order_items i JOIN gold.orders o USING (order_id)
GROUP BY i.order_id, i.seller_id;

CREATE OR REPLACE VIEW gold.sla_orders AS SELECT * FROM gold.orders WHERE sla_eligible;
