"""Load verified Azure output into Databricks Free Edition using the official CLI.

The handoff is Azure -> verified local download -> Unity Catalog volume. It is
explicitly not a native Azure Data Factory-to-Azure-Databricks connection.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "reports/databricks/ingestion"
SCHEMA = "workspace.delivery_operations"
VOLUME = "/Volumes/workspace/delivery_operations/olist_bronze/olist-v2"
TABLES = {
    "olist_customers_dataset.csv": "bronze_customers",
    "olist_geolocation_dataset.csv": "bronze_geolocation",
    "olist_order_items_dataset.csv": "bronze_order_items",
    "olist_order_payments_dataset.csv": "bronze_order_payments",
    "olist_order_reviews_dataset.csv": "bronze_order_reviews",
    "olist_orders_dataset.csv": "bronze_orders",
    "olist_products_dataset.csv": "bronze_products",
    "olist_sellers_dataset.csv": "bronze_sellers",
    "product_category_name_translation.csv": "bronze_categories",
}

SILVER_SQL = f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.silver_order_sla
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
    FROM {SCHEMA}.bronze_orders
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
FROM eligible"""

GOLD_SQL = f"""CREATE VIEW IF NOT EXISTS {SCHEMA}.gold_delivery_overview AS
SELECT count(*) AS orders,
       count_if(sla_eligible) AS sla_eligible,
       count_if(sla_eligible AND is_late) AS late_orders,
       count_if(sla_eligible AND NOT is_late) AS on_time_orders,
       100.0 * count_if(sla_eligible AND is_late) / nullif(count_if(sla_eligible), 0) AS late_rate_pct
FROM {SCHEMA}.silver_order_sla"""

MONEY_SQL = f"""WITH items AS (
    SELECT sum(cast(price AS DECIMAL(20,2))) AS item_value,
           sum(cast(freight_value AS DECIMAL(20,2))) AS freight_value
    FROM {SCHEMA}.bronze_order_items
), payments AS (
    SELECT sum(cast(payment_value AS DECIMAL(20,2))) AS payment_value
    FROM {SCHEMA}.bronze_order_payments
)
SELECT item_value, freight_value, payment_value FROM items CROSS JOIN payments"""


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def definitions(files):
    statements = [
        ("create_schema", f"CREATE SCHEMA IF NOT EXISTS {SCHEMA} COMMENT 'Delivery operations portfolio: public Olist v2 data only'"),
        ("create_volume", f"CREATE VOLUME IF NOT EXISTS {SCHEMA}.olist_bronze COMMENT 'Azure bronze files transferred through a locally verified handoff'"),
    ]
    for item in files:
        table = TABLES[item["file"]]
        columns = ", ".join("`" + column + "`" for column in item["columns"])
        schema = ", ".join("`" + column + "` STRING" for column in item["columns"])
        sql = f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.{table}
USING DELTA
COMMENT 'Original public Olist v2 file; all source fields retained as strings.'
AS SELECT {columns}
FROM read_files('{VOLUME}/{item['file']}',
    format => 'csv', schema => '{schema}', header => true,
    multiLine => true, escape => '"', mode => 'FAILFAST',
    schemaEvolutionMode => 'none')"""
        statements.append((table, sql))
    statements.extend([("silver_order_sla", SILVER_SQL), ("gold_delivery_overview", GOLD_SQL)])
    return statements


class DatabricksIngestion:
    def __init__(self, cli, profile):
        self.cli = cli
        self.profile = profile
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        self.state_path = EVIDENCE / "execution_state.json"
        self.state = read(self.state_path) if self.state_path.exists() else {"files_uploaded": [], "queries": []}
        warehouses = self.command("warehouses", "list")
        warehouse = next(w for w in warehouses if w["name"] == "Serverless Starter Warehouse")
        if not warehouse["enable_serverless_compute"] or warehouse["auto_stop_mins"] > 10:
            raise RuntimeError("Use the existing Free Edition starter warehouse with its short auto-stop setting.")
        self.warehouse_id = warehouse["id"]

    def command(self, *args, json_output=True):
        command = [str(self.cli), *args, "--profile", self.profile]
        if json_output:
            command += ["-o", "json"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Databricks CLI request failed")
        return json.loads(result.stdout) if json_output and result.stdout.strip() else result.stdout

    def statement(self, name, sql):
        request_path = EVIDENCE / (name + "_request.json")
        save(request_path, {"warehouse_id": self.warehouse_id, "statement": sql,
                            "wait_timeout": "50s", "on_wait_timeout": "CONTINUE"})
        result = self.command("api", "post", "/api/2.0/sql/statements", "--json", "@" + str(request_path))
        statement_id = result["statement_id"]
        save(EVIDENCE / (name + "_response.json"), result)
        started = time.monotonic()
        while result["status"]["state"] in {"PENDING", "RUNNING"} and time.monotonic() - started < 300:
            print(name + ": " + result["status"]["state"], flush=True)
            time.sleep(5)
            result = self.command("api", "get", "/api/2.0/sql/statements/" + statement_id)
            save(EVIDENCE / (name + "_response.json"), result)
        if result["status"]["state"] != "SUCCEEDED":
            raise RuntimeError(name + " did not succeed: " + json.dumps(result["status"]))
        self.state["queries"].append({"name": name, "statement_id": statement_id, "state": "SUCCEEDED"})
        save(self.state_path, self.state)
        print("Databricks SQL succeeded: " + name, flush=True)
        return result.get("result", {}).get("data_array", [])

    def upload_and_verify_volume(self, files):
        self.command("fs", "mkdir", "dbfs:" + VOLUME, json_output=False)
        handoff = ROOT / "data/interim/azure-bronze/olist-v2"
        download = EVIDENCE / "volume_downloads" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        download.mkdir(parents=True)
        proof = []
        for item in files:
            source = handoff / item["file"]
            remote = "dbfs:" + VOLUME + "/" + item["file"]
            if item["file"] not in self.state["files_uploaded"]:
                self.command("fs", "cp", str(source), remote, json_output=False)
                self.state["files_uploaded"].append(item["file"])
                save(self.state_path, self.state)
            local = download / item["file"]
            self.command("fs", "cp", remote, str(local), json_output=False)
            if local.stat().st_size != item["bytes"] or sha256(local) != item["sha256"]:
                raise RuntimeError("Databricks volume bytes differ from Azure/original source: " + item["file"])
            proof.append({"file": item["file"], "bytes": item["bytes"], "sha256": item["sha256"], "matches_original": True})
            print("Databricks upload/download hash matched: " + item["file"], flush=True)
        save(EVIDENCE / "volume_hash_verification.json", {"files": proof, "all_hashes_match": True,
             "handoff": "ADF bronze -> verified local download -> Databricks Unity Catalog volume"})


def original_money(files):
    totals = []
    for filename, columns in [("olist_order_items_dataset.csv", ["price", "freight_value"]),
                              ("olist_order_payments_dataset.csv", ["payment_value"])]:
        values = [Decimal("0") for _ in columns]
        with (ROOT / "data/raw/olist-v2" / filename).open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                for index, column in enumerate(columns):
                    values[index] += Decimal(row[column])
        totals.extend(values)
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["render", "execute"])
    parser.add_argument("--cli", default=shutil.which("databricks"))
    parser.add_argument("--profile", default="delivery-project")
    args = parser.parse_args()
    files = read(ROOT / "docs/raw_dataset_manifest.json")["files"]
    if len(files) != 9 or {f["file"] for f in files} != set(TABLES):
        raise RuntimeError("The approved source inventory must contain exactly the original nine Olist files.")
    statements = definitions(files)
    counts_sql = "\nUNION ALL\n".join(
        f"SELECT '{TABLES[item['file']]}' AS table_name, count(*) AS row_count FROM {SCHEMA}.{TABLES[item['file']]}"
        for item in files)
    notebook = "-- Databricks notebook source\n-- Public Olist v2. The Azure-to-Databricks handoff is explicit and locally verified.\n"
    notebook += "\n-- COMMAND ----------\n".join("-- step: " + name + "\n" + sql + ";\n" for name, sql in statements)
    notebook += "\n-- COMMAND ----------\n" + counts_sql + ";\n"
    notebook += "\n-- COMMAND ----------\nSELECT * FROM " + SCHEMA + ".gold_delivery_overview;\n"
    notebook_path = ROOT / "databricks/01_bronze_and_sla.sql"
    notebook_path.write_text(notebook, encoding="utf-8")
    if args.stage == "render":
        print("Rendered the reproducible SQL notebook; no cloud request made.")
        return
    if not args.cli:
        raise RuntimeError("Supply the installed official Databricks CLI with --cli.")
    azure_proof = read(ROOT / "reports/azure/destination_verification.json")
    if not azure_proof["all_original_hashes_match"] or azure_proof["files_verified"] != 9:
        raise RuntimeError("Verify the nine Azure destination files before this handoff.")
    for item in files:
        source = ROOT / "data/interim/azure-bronze/olist-v2" / item["file"]
        if source.stat().st_size != item["bytes"] or sha256(source) != item["sha256"]:
            raise RuntimeError("The verified Azure handoff file changed: " + item["file"])
    runner = DatabricksIngestion(args.cli, args.profile)
    for name, sql in statements[:2]:
        runner.statement(name, sql)
    runner.upload_and_verify_volume(files)
    for name, sql in statements[2:]:
        runner.statement(name, sql)
    rows = runner.statement("verify_all_row_counts", counts_sql)
    actual_counts = {row[0]: int(row[1]) for row in rows}
    expected_counts = {TABLES[item["file"]]: item["rows"] for item in files}
    if actual_counts != expected_counts:
        raise RuntimeError("Databricks Delta table counts differ from the independently verified source manifest.")
    overview = runner.statement("verify_order_sla", f"SELECT orders,sla_eligible,late_orders,on_time_orders,late_rate_pct FROM {SCHEMA}.gold_delivery_overview")[0]
    with duckdb.connect(str(ROOT / "data/interim/delivery_operations.duckdb"), read_only=True) as connection:
        baseline = connection.execute("SELECT count(*),count(*) FILTER(WHERE sla_eligible),count(*) FILTER(WHERE is_late),count(*) FILTER(WHERE sla_eligible AND NOT is_late) FROM gold.orders").fetchone()
    if [int(value) for value in overview[:4]] != list(baseline):
        raise RuntimeError("Databricks order/SLA counts differ from the independently executed local SQL pipeline.")
    money = [Decimal(value) for value in runner.statement("verify_original_money", MONEY_SQL)[0]]
    if money != original_money(files):
        raise RuntimeError("Cloud money totals do not match independent Decimal sums over the original CSVs.")
    runner.command("workspace", "mkdirs", "/Shared/Delivery_Operations", json_output=False)
    notebook_target = "/Shared/Delivery_Operations/01_Bronze_And_SLA"
    if not runner.state.get("notebook_imported"):
        runner.command("workspace", "import", notebook_target, "--file", str(notebook_path), "--format", "SOURCE", "--language", "SQL", json_output=False)
        runner.state["notebook_imported"] = True
        save(runner.state_path, runner.state)
    notebook_info = runner.command("workspace", "get-status", notebook_target)
    proof = {"verified_at": datetime.now(timezone.utc).isoformat(), "edition": "Free Edition",
        "interface": "Official CLI and SQL Statement Execution API; no console automation",
        "transfer": "Azure bronze -> hash-verified local handoff -> hash-verified Unity Catalog volume",
        "source_files_verified": 9, "source_bytes_verified": azure_proof["bytes_verified"],
        "bronze_delta_tables": len(actual_counts), "bronze_rows": sum(actual_counts.values()),
        "table_row_counts": actual_counts, "silver_orders": int(overview[0]), "sla_eligible": int(overview[1]),
        "late_orders": int(overview[2]), "on_time_orders": int(overview[3]), "late_rate_pct": overview[4],
        "money_totals_source_units": {key: str(value) for key, value in zip(["item_value", "freight_value", "payment_value"], money)},
        "independent_checks": ["Original/Azure/Databricks downloaded-file SHA-256 hashes", "All nine source-manifest row counts", "Separate DuckDB order and calendar-day SLA counts", "Decimal sums over original CSV money fields"],
        "native_adf_to_azure_databricks_integration": False,
        "sql_notebook_imported": True, "notebook_path": notebook_target, "notebook_object_id": notebook_info.get("object_id"),
        "sql_execution": "The supplied SQL definitions were executed through the SQL API; no notebook job run is claimed",
        "model_training": False}
    save(EVIDENCE / "delivery_cloud_verification.json", proof)
    print(json.dumps({key: value for key, value in proof.items() if key not in {"notebook_object_id"}}, indent=2), flush=True)


if __name__ == "__main__":
    main()
