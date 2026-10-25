-- Databricks notebook source
-- Public Olist v2. The Azure-to-Databricks handoff is explicit and locally verified.
-- step: create_schema
CREATE SCHEMA IF NOT EXISTS workspace.delivery_operations COMMENT 'Delivery operations portfolio: public Olist v2 data only';

-- COMMAND ----------
-- step: create_volume
CREATE VOLUME IF NOT EXISTS workspace.delivery_operations.olist_bronze COMMENT 'Azure bronze files transferred through a locally verified handoff';

-- COMMAND ----------
-- step: bronze_customers
CREATE TABLE IF NOT EXISTS workspace.delivery_operations.bronze_customers
USING DELTA
COMMENT 'Original public Olist v2 file; all source fields retained as strings.'
AS SELECT `customer_id`, `customer_unique_id`, `customer_zip_code_prefix`, `customer_city`, `customer_state`
FROM read_files('/Volumes/workspace/delivery_operations/olist_bronze/olist-v2/olist_customers_dataset.csv',
    format => 'csv', schema => '`customer_id` STRING, `customer_unique_id` STRING, `customer_zip_code_prefix` STRING, `customer_city` STRING, `customer_state` STRING', header => true,
    multiLine => true, escape => '"', mode => 'FAILFAST',
    schemaEvolutionMode => 'none');

-- COMMAND ----------
-- step: bronze_geolocation
CREATE TABLE IF NOT EXISTS workspace.delivery_operations.bronze_geolocation
USING DELTA
COMMENT 'Original public Olist v2 file; all source fields retained as strings.'
AS SELECT `geolocation_zip_code_prefix`, `geolocation_lat`, `geolocation_lng`, `geolocation_city`, `geolocation_state`
FROM read_files('/Volumes/workspace/delivery_operations/olist_bronze/olist-v2/olist_geolocation_dataset.csv',
    format => 'csv', schema => '`geolocation_zip_code_prefix` STRING, `geolocation_lat` STRING, `geolocation_lng` STRING, `geolocation_city` STRING, `geolocation_state` STRING', header => true,
    multiLine => true, escape => '"', mode => 'FAILFAST',
    schemaEvolutionMode => 'none');

-- COMMAND ----------
-- step: bronze_order_items
CREATE TABLE IF NOT EXISTS workspace.delivery_operations.bronze_order_items
USING DELTA
COMMENT 'Original public Olist v2 file; all source fields retained as strings.'
AS SELECT `order_id`, `order_item_id`, `product_id`, `seller_id`, `shipping_limit_date`, `price`, `freight_value`
FROM read_files('/Volumes/workspace/delivery_operations/olist_bronze/olist-v2/olist_order_items_dataset.csv',
    format => 'csv', schema => '`order_id` STRING, `order_item_id` STRING, `product_id` STRING, `seller_id` STRING, `shipping_limit_date` STRING, `price` STRING, `freight_value` STRING', header => true,
    multiLine => true, escape => '"', mode => 'FAILFAST',
    schemaEvolutionMode => 'none');

-- COMMAND ----------
-- step: bronze_order_payments
CREATE TABLE IF NOT EXISTS workspace.delivery_operations.bronze_order_payments
USING DELTA
COMMENT 'Original public Olist v2 file; all source fields retained as strings.'
AS SELECT `order_id`, `payment_sequential`, `payment_type`, `payment_installments`, `payment_value`
FROM read_files('/Volumes/workspace/delivery_operations/olist_bronze/olist-v2/olist_order_payments_dataset.csv',
    format => 'csv', schema => '`order_id` STRING, `payment_sequential` STRING, `payment_type` STRING, `payment_installments` STRING, `payment_value` STRING', header => true,
    multiLine => true, escape => '"', mode => 'FAILFAST',
    schemaEvolutionMode => 'none');

-- COMMAND ----------
-- step: bronze_order_reviews
CREATE TABLE IF NOT EXISTS workspace.delivery_operations.bronze_order_reviews
USING DELTA
COMMENT 'Original public Olist v2 file; all source fields retained as strings.'
AS SELECT `review_id`, `order_id`, `review_score`, `review_comment_title`, `review_comment_message`, `review_creation_date`, `review_answer_timestamp`
FROM read_files('/Volumes/workspace/delivery_operations/olist_bronze/olist-v2/olist_order_reviews_dataset.csv',
    format => 'csv', schema => '`review_id` STRING, `order_id` STRING, `review_score` STRING, `review_comment_title` STRING, `review_comment_message` STRING, `review_creation_date` STRING, `review_answer_timestamp` STRING', header => true,
    multiLine => true, escape => '"', mode => 'FAILFAST',
    schemaEvolutionMode => 'none');

-- COMMAND ----------
-- step: bronze_orders
CREATE TABLE IF NOT EXISTS workspace.delivery_operations.bronze_orders
USING DELTA
COMMENT 'Original public Olist v2 file; all source fields retained as strings.'
AS SELECT `order_id`, `customer_id`, `order_status`, `order_purchase_timestamp`, `order_approved_at`, `order_delivered_carrier_date`, `order_delivered_customer_date`, `order_estimated_delivery_date`
FROM read_files('/Volumes/workspace/delivery_operations/olist_bronze/olist-v2/olist_orders_dataset.csv',
    format => 'csv', schema => '`order_id` STRING, `customer_id` STRING, `order_status` STRING, `order_purchase_timestamp` STRING, `order_approved_at` STRING, `order_delivered_carrier_date` STRING, `order_delivered_customer_date` STRING, `order_estimated_delivery_date` STRING', header => true,
    multiLine => true, escape => '"', mode => 'FAILFAST',
    schemaEvolutionMode => 'none');

-- COMMAND ----------
-- step: bronze_products
CREATE TABLE IF NOT EXISTS workspace.delivery_operations.bronze_products
USING DELTA
COMMENT 'Original public Olist v2 file; all source fields retained as strings.'
AS SELECT `product_id`, `product_category_name`, `product_name_lenght`, `product_description_lenght`, `product_photos_qty`, `product_weight_g`, `product_length_cm`, `product_height_cm`, `product_width_cm`
FROM read_files('/Volumes/workspace/delivery_operations/olist_bronze/olist-v2/olist_products_dataset.csv',
    format => 'csv', schema => '`product_id` STRING, `product_category_name` STRING, `product_name_lenght` STRING, `product_description_lenght` STRING, `product_photos_qty` STRING, `product_weight_g` STRING, `product_length_cm` STRING, `product_height_cm` STRING, `product_width_cm` STRING', header => true,
    multiLine => true, escape => '"', mode => 'FAILFAST',
    schemaEvolutionMode => 'none');

-- COMMAND ----------
-- step: bronze_sellers
CREATE TABLE IF NOT EXISTS workspace.delivery_operations.bronze_sellers
USING DELTA
COMMENT 'Original public Olist v2 file; all source fields retained as strings.'
AS SELECT `seller_id`, `seller_zip_code_prefix`, `seller_city`, `seller_state`
FROM read_files('/Volumes/workspace/delivery_operations/olist_bronze/olist-v2/olist_sellers_dataset.csv',
    format => 'csv', schema => '`seller_id` STRING, `seller_zip_code_prefix` STRING, `seller_city` STRING, `seller_state` STRING', header => true,
    multiLine => true, escape => '"', mode => 'FAILFAST',
    schemaEvolutionMode => 'none');

-- COMMAND ----------
-- step: bronze_categories
CREATE TABLE IF NOT EXISTS workspace.delivery_operations.bronze_categories
USING DELTA
COMMENT 'Original public Olist v2 file; all source fields retained as strings.'
AS SELECT `product_category_name`, `product_category_name_english`
FROM read_files('/Volumes/workspace/delivery_operations/olist_bronze/olist-v2/product_category_name_translation.csv',
    format => 'csv', schema => '`product_category_name` STRING, `product_category_name_english` STRING', header => true,
    multiLine => true, escape => '"', mode => 'FAILFAST',
    schemaEvolutionMode => 'none');

-- COMMAND ----------
-- step: silver_order_sla
CREATE TABLE IF NOT EXISTS workspace.delivery_operations.silver_order_sla
USING DELTA
COMMENT 'Order-grain calendar-day delivery SLA; ineligible labels remain NULL.'
AS
WITH typed AS (
    SELECT order_id, customer_id, order_status,
           try_cast(order_purchase_timestamp AS TIMESTAMP_NTZ) AS purchased_at,
           try_cast(order_approved_at AS TIMESTAMP_NTZ) AS approved_at,
           try_cast(order_delivered_carrier_date AS TIMESTAMP_NTZ) AS carrier_at,
           try_cast(order_delivered_customer_date AS TIMESTAMP_NTZ) AS delivered_at,
           try_cast(order_estimated_delivery_date AS TIMESTAMP_NTZ) AS promised_at
    FROM workspace.delivery_operations.bronze_orders
), eligible AS (
    SELECT *, order_status = 'delivered'
       AND purchased_at IS NOT NULL AND delivered_at IS NOT NULL AND promised_at IS NOT NULL
       AND delivered_at >= purchased_at
       AND cast(promised_at AS DATE) >= cast(purchased_at AS DATE) AS sla_eligible
    FROM typed
)
SELECT *,
       CASE WHEN sla_eligible THEN cast(delivered_at AS DATE) > cast(promised_at AS DATE) END AS is_late,
       CASE WHEN sla_eligible THEN greatest(0, datediff(cast(delivered_at AS DATE), cast(promised_at AS DATE))) END AS late_calendar_days
FROM eligible;

-- COMMAND ----------
-- step: gold_delivery_overview
CREATE VIEW IF NOT EXISTS workspace.delivery_operations.gold_delivery_overview AS
SELECT count(*) AS orders,
       count_if(sla_eligible) AS sla_eligible,
       count_if(sla_eligible AND is_late) AS late_orders,
       count_if(sla_eligible AND NOT is_late) AS on_time_orders,
       100.0 * count_if(sla_eligible AND is_late) / nullif(count_if(sla_eligible), 0) AS late_rate_pct
FROM workspace.delivery_operations.silver_order_sla;

-- COMMAND ----------
SELECT 'bronze_customers' AS table_name, count(*) AS row_count FROM workspace.delivery_operations.bronze_customers
UNION ALL
SELECT 'bronze_geolocation' AS table_name, count(*) AS row_count FROM workspace.delivery_operations.bronze_geolocation
UNION ALL
SELECT 'bronze_order_items' AS table_name, count(*) AS row_count FROM workspace.delivery_operations.bronze_order_items
UNION ALL
SELECT 'bronze_order_payments' AS table_name, count(*) AS row_count FROM workspace.delivery_operations.bronze_order_payments
UNION ALL
SELECT 'bronze_order_reviews' AS table_name, count(*) AS row_count FROM workspace.delivery_operations.bronze_order_reviews
UNION ALL
SELECT 'bronze_orders' AS table_name, count(*) AS row_count FROM workspace.delivery_operations.bronze_orders
UNION ALL
SELECT 'bronze_products' AS table_name, count(*) AS row_count FROM workspace.delivery_operations.bronze_products
UNION ALL
SELECT 'bronze_sellers' AS table_name, count(*) AS row_count FROM workspace.delivery_operations.bronze_sellers
UNION ALL
SELECT 'bronze_categories' AS table_name, count(*) AS row_count FROM workspace.delivery_operations.bronze_categories;

-- COMMAND ----------
SELECT * FROM workspace.delivery_operations.gold_delivery_overview;
