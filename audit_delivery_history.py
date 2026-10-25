"""Independently check prepared history features with direct source-table SQL."""
from pathlib import Path
import argparse
import json

import duckdb
import numpy as np
import pandas as pd

from delivery_pipeline import write_json

ROOT = Path(__file__).resolve().parent


def audit(run_id):
    run_dir = ROOT / "reports/modeling" / run_id
    original = json.loads((run_dir / "feature_audit.json").read_text())
    features = pd.read_parquet(ROOT / original["data_directory"] / "features.parquet")
    metadata = pd.read_parquet(ROOT / original["data_directory"] / "metadata.parquet")
    positions = np.linspace(0, len(features) - 1, 40, dtype=int)
    selected = list(features.index[positions]) + list(features.index[features["seller_count"] > 1][:10])
    checked = []
    with duckdb.connect(str(ROOT / "data/interim/delivery_operations.duckdb"), read_only=True) as connection:
        connection.execute("SET threads=2")
        for order_id in dict.fromkeys(selected):
            moment = metadata.loc[order_id, "approved_at"].to_pydatetime()
            expected = {}
            for days in [30, 90]:
                number, late = connection.execute("""
                    SELECT count(*),coalesce(sum(cast(is_late AS INTEGER)),0)
                    FROM gold.orders WHERE sla_eligible
                    AND (approved_at IS NULL OR approved_at<=delivered_at)
                    AND delivered_at>=?::TIMESTAMP-?*INTERVAL '1 day' AND delivered_at<?::TIMESTAMP
                    """, [moment, days, moment]).fetchone()
                expected[f"global_completed_{days}d"] = number
                expected[f"global_late_rate_{days}d"] = (late + 1) / (number + 2)
            expected["global_approvals_7d"] = connection.execute("""
                SELECT count(*) FROM gold.orders WHERE approved_at>=purchased_at
                AND approved_at>=?::TIMESTAMP-INTERVAL '7 days' AND approved_at<?::TIMESTAMP
                """, [moment, moment]).fetchone()[0]
            sellers = connection.execute("SELECT DISTINCT seller_id FROM gold.order_items WHERE order_id=?", [order_id]).fetchall()
            counts, rates, demand7, demand30 = [], [], [], []
            for (seller,) in sellers:
                number, late = connection.execute("""
                    SELECT count(*),coalesce(sum(cast(o.is_late AS INTEGER)),0)
                    FROM gold.order_sellers s JOIN gold.orders o USING(order_id)
                    WHERE s.seller_id=? AND o.sla_eligible
                    AND (o.approved_at IS NULL OR o.approved_at<=o.delivered_at)
                    AND o.delivered_at>=?::TIMESTAMP-INTERVAL '90 days' AND o.delivered_at<?::TIMESTAMP
                    """, [seller, moment, moment]).fetchone()
                counts.append(number)
                rates.append((late + 20 * expected["global_late_rate_90d"]) / (number + 20))
                for days, output in [(7, demand7), (30, demand30)]:
                    output.append(connection.execute("""
                        SELECT count(*) FROM gold.order_sellers s JOIN gold.orders o USING(order_id)
                        WHERE s.seller_id=? AND o.approved_at>=o.purchased_at
                        AND o.approved_at>=?::TIMESTAMP-?*INTERVAL '1 day' AND o.approved_at<?::TIMESTAMP
                        """, [seller, moment, days, moment]).fetchone()[0])
            expected.update({"seller_completed_90d_mean": np.mean(counts), "seller_completed_90d_min": min(counts),
                             "seller_late_rate_90d_mean": np.mean(rates), "seller_late_rate_90d_max": max(rates),
                             "seller_cold_start_fraction": np.mean(np.asarray(counts) == 0),
                             "seller_approvals_7d_mean": np.mean(demand7), "seller_approvals_7d_max": max(demand7),
                             "seller_approvals_30d_mean": np.mean(demand30), "seller_approvals_30d_max": max(demand30)})
            for column, value in expected.items():
                if not np.isclose(features.loc[order_id, column], value, rtol=0, atol=1e-10):
                    raise ValueError(f"Independent history mismatch for {column} in {order_id}")
            checked.append({"order_id": order_id, "approved_at": str(moment), "distinct_sellers": len(sellers),
                            "history_features_checked": len(expected), "passed": True})
    result = {"passed": True, "method": "Direct source-table SQL independent of the NumPy history implementation",
              "orders_checked": len(checked), "feature_values_checked": sum(row["history_features_checked"] for row in checked),
              "samples": checked}
    write_json(run_dir / "independent_history_audit.json", result)
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    audit(parser.parse_args().run_id)
