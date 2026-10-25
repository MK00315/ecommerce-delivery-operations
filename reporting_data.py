"""Read-only reporting exports, shared by the local Excel and Power BI artifacts."""
from pathlib import Path
import json

import duckdb
import pandas as pd

from delivery_pipeline import sha256, write_json

ROOT = Path(__file__).resolve().parent


def prepare(root=ROOT):
    operation = json.loads((root / "reports/operations/latest_completed.json").read_text())
    operation_dir = root / operation["report_directory"]
    if not isinstance(operation["verification"], dict):
        raise ValueError("Independently verified operations results are required.")
    model = json.loads((root / "reports/modeling/latest_completed.json").read_text())
    out = root / "reports/reporting"
    out.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(root / "data/interim/delivery_operations.duckdb"), read_only=True) as con:
        monthly = con.execute("""SELECT purchase_month,
            count(*) orders,count(*) FILTER(WHERE sla_eligible) eligible,
            count(*) FILTER(WHERE is_late) late,
            count(*) FILTER(WHERE NOT sla_eligible OR sla_eligible IS NULL) AS "unknown",
            sum(delivery_days) FILTER(WHERE sla_eligible) delivered_days_sum,
            median(delivery_days) FILTER(WHERE sla_eligible) median_delivery_days
            FROM gold.orders GROUP BY 1 ORDER BY 1 NULLS LAST""").df()
        states = con.execute("""SELECT coalesce(customer_state,'Unknown') state,
            count(*) orders,count(*) FILTER(WHERE sla_eligible) eligible,
            count(*) FILTER(WHERE is_late) late,
            sum(delivery_days) FILTER(WHERE sla_eligible) delivered_days_sum
            FROM gold.orders GROUP BY 1 ORDER BY count(*) DESC,1""").df()
        facts = con.execute("""SELECT order_id AS "Order ID",purchase_date AS "Purchase Date",
            coalesce(customer_state,'Unknown') AS "Customer State",order_status AS "Final Status",
            cast(coalesce(sla_eligible,false) AS INTEGER) AS "SLA Eligible",
            CASE WHEN sla_eligible THEN cast(is_late AS INTEGER) END AS "Late Flag",
            CASE WHEN sla_eligible THEN delivery_days END AS "Delivery Days",
            item_count AS "Item Count",seller_count AS "Seller Count",
            promised_calendar_days AS "Promised Days",max_distance_km AS "Distance Km",
            cast(item_count>0 AND items_with_distance=item_count AS INTEGER) AS "Distance Complete"
            FROM gold.orders ORDER BY order_id""").df()
    assert facts["Order ID"].is_unique and len(facts) == 99441
    assert facts["SLA Eligible"].sum() == 96470 and facts["Late Flag"].sum() == 6534
    assert facts["Late Flag"].isna().sum() == 2971
    for frame in [monthly, states]:
        assert int(frame["orders"].sum()) == 99441 and int(frame["eligible"].sum()) == 96470
        assert int(frame["late"].sum()) == 6534
    daily = pd.read_csv(operation_dir / "daily_policy_results.csv")
    scenarios = pd.read_csv(operation_dir / "scenario_summary.csv")
    contrasts = pd.read_csv(operation_dir / "statistical_contrasts.csv")
    # Missing medians/elapsed sums retain their missing status in source tables.
    records = lambda frame: json.loads(frame.to_json(orient="records", date_format="iso", double_precision=15))
    for name, frame in [("orders", facts), ("monthly", monthly), ("states", states),
                        ("daily_reviews", daily), ("scenarios", scenarios), ("contrasts", contrasts)]:
        frame.to_csv(out / f"{name}.csv", index=False, date_format="%Y-%m-%d")
    data = {"monthly": records(monthly), "states": records(states), "daily": records(daily),
            "scenarios": records(scenarios), "contrasts": records(contrasts),
            "operation_run": operation["run_id"], "model_run": model["run_id"],
            "source": "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce",
            "control": {"orders": 99441, "eligible": 96470, "late": 6534, "unknown": 2971,
                        "batches": 28, "candidate_orders": 6590, "candidate_unknown": 103,
                        "default_selected": 721, "default_known_late": 79},
            "provenance": {"database_sha256": sha256(root / "data/interim/delivery_operations.duckdb"),
                           "operations_verification_sha256": sha256(root / "docs/OPERATIONS_VERIFICATION.json"),
                           "model_sha256": operation["provenance"]["model_sha256"]}}
    write_json(out / "workbook_inputs.json", data)
    manifest = {"executed": "Local read-only reporting exports", "source_order_rows": len(facts),
                "operations_run": operation["run_id"], "provenance": data["provenance"],
                "files": {path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)} for path in out.glob("*.csv")}}
    write_json(out / "reporting_manifest.json", manifest)
    print(json.dumps({"reporting_exports": len(manifest["files"]), "order_rows": len(facts),
                      "monthly_rows": len(monthly), "state_rows": len(states), "daily_rows": len(daily)}, indent=2))
    return data


if __name__ == "__main__":
    prepare()
