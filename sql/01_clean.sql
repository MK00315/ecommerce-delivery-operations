-- Preserve raw tables. Typed silver tables retain missing and anomalous observations.
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

CREATE OR REPLACE MACRO postcode(z) AS
    CASE WHEN regexp_full_match(trim(z), '[0-9]{1,5}') THEN lpad(trim(z), 5, '0') ELSE NULL END;
CREATE OR REPLACE MACRO sla_late(promised, arrived) AS
    CASE WHEN promised IS NULL OR arrived IS NULL THEN NULL
         ELSE CAST(arrived AS DATE) > CAST(promised AS DATE) END;
CREATE OR REPLACE MACRO great_circle_km(lat1, lon1, lat2, lon2) AS
    CASE WHEN lat1 IS NULL OR lon1 IS NULL OR lat2 IS NULL OR lon2 IS NULL THEN NULL
    ELSE 2 * 6371.0088 * asin(sqrt(least(1.0, greatest(0.0,
         pow(sin(radians((lat2-lat1)/2)), 2)
         + cos(radians(lat1))*cos(radians(lat2))*pow(sin(radians((lon2-lon1)/2)), 2))))) END;

CREATE OR REPLACE TABLE silver.postcodes AS
SELECT postcode(geolocation_zip_code_prefix) AS postcode_prefix,
       median(try_cast(geolocation_lat AS DOUBLE)) AS latitude,
       median(try_cast(geolocation_lng AS DOUBLE)) AS longitude,
       count(*) AS coordinate_observations
FROM raw.geolocation
WHERE postcode(geolocation_zip_code_prefix) IS NOT NULL
  AND try_cast(geolocation_lat AS DOUBLE) BETWEEN -34 AND 6
  AND try_cast(geolocation_lng AS DOUBLE) BETWEEN -74 AND -34
GROUP BY 1;

CREATE OR REPLACE TABLE silver.customers AS
SELECT trim(customer_id) AS customer_id, trim(customer_unique_id) AS customer_unique_id,
       postcode(customer_zip_code_prefix) AS postcode_prefix,
       lower(trim(customer_city)) AS city, upper(trim(customer_state)) AS state,
       g.latitude, g.longitude
FROM raw.customers c
LEFT JOIN silver.postcodes g ON postcode(c.customer_zip_code_prefix) = g.postcode_prefix;

CREATE OR REPLACE TABLE silver.sellers AS
SELECT trim(seller_id) AS seller_id, postcode(seller_zip_code_prefix) AS postcode_prefix,
       lower(trim(seller_city)) AS city, upper(trim(seller_state)) AS state,
       g.latitude, g.longitude
FROM raw.sellers s
LEFT JOIN silver.postcodes g ON postcode(s.seller_zip_code_prefix) = g.postcode_prefix;

CREATE OR REPLACE TABLE silver.products AS
SELECT trim(p.product_id) AS product_id,
       coalesce(nullif(trim(p.product_category_name), ''), 'unknown') AS category_original,
       coalesce(nullif(trim(t.product_category_name_english), ''), nullif(trim(p.product_category_name), ''), 'unknown') AS category,
       try_cast(product_name_lenght AS INTEGER) AS name_length,
       try_cast(product_description_lenght AS INTEGER) AS description_length,
       try_cast(product_photos_qty AS INTEGER) AS photo_count,
       CASE WHEN try_cast(product_weight_g AS DOUBLE) > 0 THEN try_cast(product_weight_g AS DOUBLE) END AS weight_g,
       CASE WHEN try_cast(product_length_cm AS DOUBLE) > 0 THEN try_cast(product_length_cm AS DOUBLE) END AS length_cm,
       CASE WHEN try_cast(product_height_cm AS DOUBLE) > 0 THEN try_cast(product_height_cm AS DOUBLE) END AS height_cm,
       CASE WHEN try_cast(product_width_cm AS DOUBLE) > 0 THEN try_cast(product_width_cm AS DOUBLE) END AS width_cm
FROM raw.products p
LEFT JOIN raw.categories t ON p.product_category_name = t.product_category_name;

CREATE OR REPLACE TABLE silver.orders AS
SELECT trim(order_id) AS order_id, trim(customer_id) AS customer_id,
       lower(trim(order_status)) AS order_status,
       try_cast(order_purchase_timestamp AS TIMESTAMP) AS purchased_at,
       try_cast(order_approved_at AS TIMESTAMP) AS approved_at,
       try_cast(order_delivered_carrier_date AS TIMESTAMP) AS carrier_at,
       try_cast(order_delivered_customer_date AS TIMESTAMP) AS delivered_at,
       try_cast(order_estimated_delivery_date AS TIMESTAMP) AS promised_at
FROM raw.orders;

CREATE OR REPLACE TABLE silver.items AS
SELECT trim(order_id) AS order_id, try_cast(order_item_id AS INTEGER) AS item_number,
       trim(product_id) AS product_id, trim(seller_id) AS seller_id,
       try_cast(shipping_limit_date AS TIMESTAMP) AS shipping_limit_at,
       try_cast(price AS DECIMAL(18,2)) AS item_value,
       try_cast(freight_value AS DECIMAL(18,2)) AS freight_value
FROM raw.items;

CREATE OR REPLACE TABLE silver.payments AS
SELECT trim(order_id) AS order_id, try_cast(payment_sequential AS INTEGER) AS payment_number,
       lower(trim(payment_type)) AS payment_type,
       try_cast(payment_installments AS INTEGER) AS installments,
       try_cast(payment_value AS DECIMAL(18,2)) AS payment_value
FROM raw.payments;

-- Review IDs are reused across some orders. Keep the unique (order_id, review_id) pairs.
-- Review text is unnecessary for this tabular project and is not copied to silver.
CREATE OR REPLACE TABLE silver.reviews AS
SELECT trim(order_id) AS order_id, trim(review_id) AS review_id,
       try_cast(review_score AS INTEGER) AS review_score,
       try_cast(review_creation_date AS TIMESTAMP) AS created_at,
       try_cast(review_answer_timestamp AS TIMESTAMP) AS answered_at
FROM raw.reviews;

CREATE OR REPLACE TABLE silver.latest_reviews AS
SELECT order_id, review_id, review_score, created_at, answered_at,
       count(*) OVER (PARTITION BY order_id) AS review_count
FROM silver.reviews
QUALIFY row_number() OVER (
    PARTITION BY order_id ORDER BY answered_at DESC NULLS LAST,
    created_at DESC NULLS LAST, review_id ASC
) = 1;
