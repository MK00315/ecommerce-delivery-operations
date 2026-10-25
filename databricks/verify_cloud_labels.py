"""Compare exact order/label membership between Databricks and local DuckDB."""

import argparse
import hashlib
import shutil
from datetime import datetime, timezone

import duckdb

from run_cloud_ingestion import DatabricksIngestion, EVIDENCE, ROOT, read, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default=shutil.which("databricks"))
    parser.add_argument("--profile", default="delivery-project")
    args = parser.parse_args()
    if not args.cli:
        raise RuntimeError("Supply the installed official Databricks CLI.")
    runner = DatabricksIngestion(args.cli, args.profile)
    sql = (ROOT / "databricks/02_verify_label_membership.sql").read_text(encoding="utf-8")
    actual = runner.statement("verify_exact_label_membership", sql)[0]
    groups = [("all_orders", "TRUE"), ("sla_eligible", "sla_eligible"),
              ("late", "is_late"), ("on_time", "sla_eligible AND NOT is_late")]
    comparisons = []
    with duckdb.connect(str(ROOT / "data/interim/delivery_operations.duckdb"), read_only=True) as connection:
        for index, (name, condition) in enumerate(groups):
            ids = [row[0] for row in connection.execute(
                "SELECT order_id FROM gold.orders WHERE " + condition + " ORDER BY order_id").fetchall()]
            expected = hashlib.sha256(",".join(ids).encode("utf-8")).hexdigest()
            if actual[index] != expected:
                raise RuntimeError("The Databricks membership differs for " + name)
            comparisons.append({"group": name, "orders": len(ids), "sha256": expected, "matches_local_duckdb": True})
    proof = {"verified_at": datetime.now(timezone.utc).isoformat(), "all_memberships_match": True,
             "method": "SHA-256 over sorted comma-separated order IDs, computed independently in Spark SQL and Python/DuckDB",
             "groups": comparisons}
    save(EVIDENCE / "label_membership_verification.json", proof)
    summary_path = EVIDENCE / "delivery_cloud_verification.json"
    summary = read(summary_path)
    summary["exact_order_and_label_membership_verified"] = True
    summary["independent_checks"].append("Exact all-order, SLA-eligible, late and on-time membership SHA-256 hashes")
    save(summary_path, summary)
    print("All four exact order/label membership hashes matched the independent local pipeline.")


if __name__ == "__main__":
    main()
