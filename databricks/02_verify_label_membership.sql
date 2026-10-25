-- Compare these deterministic membership hashes with the independently executed
-- local DuckDB mart. Matching totals alone would not establish matching labels.
SELECT
    sha2(concat_ws(',', sort_array(collect_list(order_id))), 256) AS all_order_ids_sha256,
    sha2(concat_ws(',', sort_array(collect_list(if(sla_eligible, order_id, NULL)))), 256) AS eligible_ids_sha256,
    sha2(concat_ws(',', sort_array(collect_list(if(is_late, order_id, NULL)))), 256) AS late_ids_sha256,
    sha2(concat_ws(',', sort_array(collect_list(if(sla_eligible AND NOT is_late, order_id, NULL)))), 256) AS on_time_ids_sha256
FROM workspace.delivery_operations.silver_order_sla;
