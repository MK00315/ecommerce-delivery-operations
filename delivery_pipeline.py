"""Verified Olist raw -> typed tables -> order/item/seller marts -> SQL reports."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import time

import duckdb

VERSION = "1.0.0"
FILES = {
    "olist_customers_dataset.csv": "customers",
    "olist_geolocation_dataset.csv": "geolocation",
    "olist_order_items_dataset.csv": "items",
    "olist_order_payments_dataset.csv": "payments",
    "olist_order_reviews_dataset.csv": "reviews",
    "olist_orders_dataset.csv": "orders",
    "olist_products_dataset.csv": "products",
    "olist_sellers_dataset.csv": "sellers",
    "product_category_name_translation.csv": "categories",
}
EXPORTS = {
    "orders": "gold.orders", "order_items": "gold.order_items",
    "order_sellers": "gold.order_sellers", "customers": "silver.customers",
    "sellers": "silver.sellers", "products": "silver.products",
    "postcodes": "silver.postcodes", "latest_reviews": "silver.latest_reviews",
}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str, allow_nan=False) + "\n", encoding="utf-8")


def source_manifest(root: Path):
    manifest = json.loads((root / "docs/raw_dataset_manifest.json").read_text(encoding="utf-8"))
    assert {entry["file"] for entry in manifest["files"]} == set(FILES), "Unexpected source file set"
    for entry in manifest["files"]:
        path = root / "data/raw/olist-v2" / entry["file"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            raise ValueError(f"Source verification failed: {entry['file']}")
    return manifest


def load_raw(connection, root: Path, manifest):
    connection.execute("CREATE SCHEMA raw")
    for entry in manifest["files"]:
        name = FILES[entry["file"]]
        path = root / "data/raw/olist-v2" / entry["file"]
        connection.execute(f"CREATE TABLE raw.{name} AS SELECT * FROM read_csv(?, header=true, all_varchar=true)", [str(path)])
        assert connection.execute(f"SELECT count(*) FROM raw.{name}").fetchone()[0] == entry["rows"], name
        actual_columns = [column[0] for column in connection.execute(f"DESCRIBE raw.{name}").fetchall()]
        assert actual_columns == entry["columns"], (name, actual_columns)


def scalar(connection, sql):
    return connection.execute(sql).fetchone()[0]


def validate_keys(connection):
    controls = []
    for table, keys in {
        "customers": ["customer_id"], "sellers": ["seller_id"], "products": ["product_id"],
        "orders": ["order_id"], "items": ["order_id", "item_number"],
        "payments": ["order_id", "payment_number"], "reviews": ["order_id", "review_id"],
        "postcodes": ["postcode_prefix"], "latest_reviews": ["order_id"],
    }.items():
        columns = ",".join(keys)
        nulls = " OR ".join(f"{key} IS NULL" for key in keys)
        duplicate_groups = scalar(connection, f"SELECT count(*) FROM (SELECT {columns} FROM silver.{table} GROUP BY {columns} HAVING count(*) > 1)")
        null_keys = scalar(connection, f"SELECT count(*) FROM silver.{table} WHERE {nulls}")
        controls.append({"table": f"silver.{table}", "keys": keys, "duplicate_groups": duplicate_groups, "null_keys": null_keys})
        if duplicate_groups or null_keys:
            raise ValueError(f"Key validation failed: silver.{table}")
    return controls


def validate_marts(connection):
    controls = {}
    for output, raw, keys in [("orders", "orders", "order_id"), ("order_items", "items", "(order_id,item_number)")]:
        rows = scalar(connection, f"SELECT count(*) FROM gold.{output}")
        source = scalar(connection, f"SELECT count(*) FROM raw.{raw}")
        unique_rows = scalar(connection, f"SELECT count(DISTINCT {keys}) FROM gold.{output}")
        assert rows == source == unique_rows, (output, rows, source, unique_rows)
        controls[output + "_rows_preserved"] = rows
    assert scalar(connection, "SELECT count(*)-count(DISTINCT (order_id,seller_id)) FROM gold.order_sellers") == 0
    for source_table, source_column, fact_column in [
        ("items", "price", "item_value"), ("items", "freight_value", "freight_value"),
        ("payments", "payment_value", "recorded_payment_value"),
    ]:
        expected = scalar(connection, f"SELECT sum(try_cast({source_column} AS DECIMAL(18,2))) FROM raw.{source_table}")
        actual = scalar(connection, f"SELECT sum({fact_column}) FROM gold.orders")
        assert expected == actual and isinstance(actual, Decimal), (fact_column, expected, actual)
        controls[fact_column + "_reconciled"] = str(actual)
    assert scalar(connection, "SELECT count(*) FROM gold.orders WHERE NOT sla_eligible AND is_late IS NOT NULL") == 0
    assert scalar(connection, "SELECT count(*) FROM gold.orders WHERE is_late AND late_calendar_days < 1") == 0
    controls["unknown_outcomes_not_treated_as_on_time"] = True
    return controls


def quality_report(connection, keys, reconciliations):
    orphan_checks = {}
    for label, child, parent, key in [
        ("orders_without_customer", "orders", "customers", "customer_id"),
        ("items_without_order", "items", "orders", "order_id"),
        ("items_without_product", "items", "products", "product_id"),
        ("items_without_seller", "items", "sellers", "seller_id"),
        ("payments_without_order", "payments", "orders", "order_id"),
        ("reviews_without_order", "reviews", "orders", "order_id"),
    ]:
        orphan_checks[label] = scalar(connection, f"SELECT count(*) FROM silver.{child} c LEFT JOIN silver.{parent} p USING({key}) WHERE p.{key} IS NULL")
    return {
        "key_controls": keys, "marts": reconciliations, "orphan_rows": orphan_checks,
        "review_rows_retained": scalar(connection, "SELECT count(*) FROM silver.reviews"),
        "review_id_reuse_excess_rows": scalar(connection, "SELECT count(*)-count(DISTINCT review_id) FROM silver.reviews"),
        "additional_reviews_on_same_order": scalar(connection, "SELECT count(*)-count(DISTINCT order_id) FROM silver.reviews"),
        "geolocation_rows_outside_broad_brazil_bounds": scalar(connection, "SELECT count(*) FROM raw.geolocation WHERE NOT (try_cast(geolocation_lat AS DOUBLE) BETWEEN -34 AND 6 AND try_cast(geolocation_lng AS DOUBLE) BETWEEN -74 AND -34)"),
        "geolocation_rows_used": scalar(connection, "SELECT sum(coordinate_observations) FROM silver.postcodes"),
        "orders_without_known_distance": scalar(connection, "SELECT count(*) FROM gold.orders WHERE max_distance_km IS NULL"),
        "orders_with_invalid_stage_sequence": scalar(connection, "SELECT count(*) FROM gold.orders WHERE invalid_stage_sequence"),
        "negative_or_missing_product_weights": scalar(connection, "SELECT count(*) FROM raw.products WHERE try_cast(product_weight_g AS DOUBLE) IS NULL OR try_cast(product_weight_g AS DOUBLE) <= 0"),
    }


def analyses(connection, root: Path, run_dir: Path):
    text = (root / "sql/03_business_analysis.sql").read_text(encoding="utf-8")
    results = {}
    for name, sql in re.findall(r"-- name: ([a-z_]+)\s*\n(.*?)(?=\n-- name:|\Z)", text, re.S):
        cursor = connection.execute(sql)
        columns = [item[0] for item in cursor.description]
        rows = cursor.fetchall()
        path = run_dir / "sql" / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
            writer.writerows(rows)
        results[name] = {"rows": len(rows), "columns": columns, "data": [dict(zip(columns, row)) for row in rows]}
    assert len(results) == 12, "An analysis was not executed"
    return results


def run_pipeline(root: Path):
    root = root.resolve()
    started = time.perf_counter()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = root / "reports/runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    interim = root / "data/interim"
    interim.mkdir(parents=True, exist_ok=True)
    build_path = interim / f"delivery_operations_build_{run_id}.duckdb"
    output_db = interim / "delivery_operations.duckdb"
    manifest = source_manifest(root)
    connection = duckdb.connect(str(build_path))
    connection.execute("SET memory_limit='2GB'")
    connection.execute("SET threads=4")
    try:
        load_raw(connection, root, manifest)
        connection.execute((root / "sql/01_clean.sql").read_text(encoding="utf-8"))
        keys = validate_keys(connection)
        connection.execute((root / "sql/02_marts.sql").read_text(encoding="utf-8"))
        reconciliations = validate_marts(connection)
        quality = quality_report(connection, keys, reconciliations)
        results = analyses(connection, root, run_dir)
        export_dir = root / "data/processed"
        export_dir.mkdir(parents=True, exist_ok=True)
        exports = []
        for name, table in EXPORTS.items():
            destination = export_dir / (name + ".parquet")
            escaped = str(destination).replace("'", "''")
            connection.execute(f"COPY (SELECT * FROM {table}) TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)")
            exports.append({"file": destination.relative_to(root).as_posix(), "table": table,
                            "rows": scalar(connection, f"SELECT count(*) FROM {table}"), "sha256": sha256(destination)})
        quality["passed"] = True
        write_json(run_dir / "data_quality.json", quality)
        write_json(run_dir / "analysis_results.json", results)
        write_json(run_dir / "processed_manifest.json", exports)
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
    if output_db.exists():
        backup = interim / "backups" / f"delivery_operations_{run_id}.duckdb"
        backup.parent.mkdir(parents=True, exist_ok=True)
        output_db.replace(backup)
    build_path.replace(output_db)
    summary = {"pipeline_version": VERSION, "run_id": run_id,
               "completed_at": datetime.now().astimezone().isoformat(), "duckdb_version": duckdb.__version__,
               "database": output_db.relative_to(root).as_posix(), "run_directory": run_dir.relative_to(root).as_posix(),
               "source_files_verified": len(FILES), "source_rows": sum(e["rows"] for e in manifest["files"]),
               "analysis_count": len(results), "parquet_exports": len(exports),
               "overview": results["overview"]["data"][0], "data_quality_passed": True,
               "elapsed_seconds": round(time.perf_counter() - started, 2),
               "cloud_execution": False, "model_training": False}
    write_json(run_dir / "run_summary.json", summary)
    write_json(root / "reports/latest_run.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    arguments = parser.parse_args()
    print(json.dumps(run_pipeline(arguments.root), indent=2, default=str))
