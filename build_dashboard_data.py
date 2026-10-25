"""Create a compact, fully reconciled read-only web snapshot from verified results."""
from datetime import datetime
import hashlib
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data/dashboard"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    reporting = ROOT / "reports/reporting"
    manifest = json.loads((reporting / "reporting_manifest.json").read_text())
    operations = json.loads((ROOT / "reports/operations/latest_completed.json").read_text())
    model = json.loads((ROOT / "reports/modeling/latest_completed.json").read_text())
    source = ROOT / "reports/operations" / operations["run_id"]
    if manifest["operations_run"] != operations["run_id"]:
        raise ValueError("Reporting and operations snapshots differ; refresh the reporting exports first.")
    for name, expected in manifest["files"].items():
        if digest(reporting / name) != expected["sha256"]:
            raise ValueError("Reporting input changed: " + name)
    if digest(ROOT / operations["provenance"]["replay_path"]) != operations["provenance"]["replay_sha256"]:
        raise ValueError("Model replay hash mismatch.")
    OUT.mkdir(parents=True, exist_ok=True)
    temporary = OUT / "delivery.building.duckdb"
    if temporary.exists():
        temporary.unlink()
    with duckdb.connect(str(temporary)) as con:
        con.execute("""CREATE TABLE orders AS SELECT
            "Order ID"::VARCHAR order_id,"Purchase Date"::DATE purchase_date,
            "Customer State"::VARCHAR customer_state,"Final Status"::VARCHAR final_status,
            "SLA Eligible"::BOOLEAN sla_eligible,"Late Flag"::BOOLEAN is_late,
            "Delivery Days"::DOUBLE delivery_days,"Item Count"::INTEGER item_count,
            "Seller Count"::INTEGER seller_count,"Promised Days"::INTEGER promised_days,
            "Distance Km"::DOUBLE distance_km,"Distance Complete"::BOOLEAN distance_complete,
            CASE WHEN NOT coalesce("Distance Complete"::BOOLEAN,false) THEN 'Unknown / incomplete'
                 WHEN "Distance Km"::DOUBLE<=500 THEN 'Up to 500 km'
                 WHEN "Distance Km"::DOUBLE<=1000 THEN '500-1,000 km'
                 WHEN "Distance Km"::DOUBLE<=2000 THEN '1,000-2,000 km' ELSE 'Over 2,000 km' END distance_group,
            CASE WHEN "Item Count"::INTEGER=0 THEN 'Missing basket' WHEN "Item Count"::INTEGER=1 THEN '1 item'
                 WHEN "Item Count"::INTEGER<=3 THEN '2-3 items' ELSE '4+ items' END basket_group
            FROM read_csv(?,header=true)""", [str(reporting / "orders.csv")])
        for table, path in [("review_candidates", source / "review_candidates.parquet"),
                            ("saved_selections", source / "selected_orders.parquet")]:
            con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_parquet(?)", [str(path)])
        con.execute("""CREATE TABLE outcomes AS SELECT order_id,observed_label_by_cutoff
                       FROM read_parquet(?)""", [str(ROOT / operations["provenance"]["replay_path"])])
        for table, name in [("daily_saved", "daily_reviews.csv"), ("scenario_saved", "scenarios.csv")]:
            con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv(?,header=true)", [str(reporting / name)])
        counts = con.execute("""SELECT count(*),count(DISTINCT order_id),count(*) FILTER(WHERE sla_eligible),
                              count(*) FILTER(WHERE is_late),count(*) FILTER(WHERE is_late IS NULL) FROM orders""").fetchone()
        if counts != (99441, 99441, 96470, 6534, 2971):
            raise ValueError("Web order counts do not reconcile.")
        candidates = con.execute("""SELECT count(*),count(DISTINCT order_id),count(DISTINCT batch_cutoff)
                                    FROM review_candidates""").fetchone()
        if candidates != (6590, 6590, 28):
            raise ValueError("Web candidate counts do not reconcile.")
        default = con.execute("""SELECT selected_orders,used_minutes,selected_unknown_outcomes,selected_known_late
            FROM scenario_saved WHERE scenario='capacity_120_cost_1' AND policy='optimized'""").fetchone()
        if default != (721, 3314, 24, 79):
            raise ValueError("Web saved planning totals do not reconcile.")
        # A saved policy can never contain an order absent from its decision batch.
        if con.execute("""SELECT count(*) FROM saved_selections s LEFT JOIN review_candidates c
                          ON s.order_id=c.order_id AND s.batch_cutoff=c.batch_cutoff WHERE c.order_id IS NULL""").fetchone()[0]:
            raise ValueError("A saved selection is outside its candidate batch.")
        con.execute("CREATE UNIQUE INDEX order_key ON orders(order_id)")
        con.execute("CREATE UNIQUE INDEX candidate_key ON review_candidates(order_id)")
        con.execute("CHECKPOINT")
    target = OUT / "delivery_dashboard.duckdb"
    temporary.replace(target)
    record = {
        "built_at": datetime.now().astimezone().isoformat(), "source_orders": 99441,
        "eligible_deliveries": 96470, "late_deliveries": 6534, "outside_sla_cohort": 2971,
        "candidate_orders": 6590, "batch_count": 28, "source_data_sampled": False,
        "operations_run": operations["run_id"], "model_run": model["run_id"],
        "snapshot_sha256": digest(target), "snapshot_bytes": target.stat().st_size,
        "source_provenance": operations["provenance"],
        "statistics": operations["statistics"]["results"],
        "model": {"inputs": 31, "final_fit_orders": 83848,
                  "diagnostic": model["august_diagnostic"], "raw_diagnostic": model["raw_august_diagnostic"],
                  "baselines": model["august_baselines"], "production_qualified": False,
                  "independent_new_period_validation": False, "limitations": model["limitations"]},
        "storage": "Read-only analytical snapshot. Filters and custom plans are computed in memory and not saved.",
    }
    (OUT / "snapshot_manifest.json").write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"passed": True, "source_orders": 99441, "candidates": 6590,
                      "bytes": target.stat().st_size, "sha256": record["snapshot_sha256"]}, indent=2))
    return record


if __name__ == "__main__":
    build()
