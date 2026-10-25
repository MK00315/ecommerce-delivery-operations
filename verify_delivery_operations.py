"""Independent source/selection checks and final QA evidence for an operations run."""
from __future__ import annotations

import argparse
from datetime import datetime
import itertools
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import duckdb
import numpy as np
import pandas as pd

from delivery_pipeline import sha256, write_json
from delivery_planner import ReviewLimits, optimize_reviews
from delivery_statistics import month_adjusted_contrast
from run_delivery_operations import load_inputs, ROOT


def brute_force(batch, minutes, count_cap, seller_cap):
    costs = batch["review_minutes"].to_numpy()
    values = batch["priority_points"].to_numpy()
    sellers = batch["primary_seller_id"].to_numpy()
    optimum = 0.0
    for bits in itertools.product([0, 1], repeat=len(batch)):
        flags = np.asarray(bits, dtype=bool)
        if flags.sum() <= count_cap and costs[flags].sum() <= minutes:
            _, counts = np.unique(sellers[flags], return_counts=True)
            if not len(counts) or counts.max() <= seller_cap:
                optimum = max(optimum, float(values[flags].sum()))
    return optimum


def verify(root, xml_path, output):
    result = json.loads((root / "reports/operations/latest_completed.json").read_text())
    directory = root / result["report_directory"]
    protocol = json.loads((directory / "protocol.json").read_text())
    for name, expected in result["source_code_sha256"].items():
        if sha256(directory / "source_snapshot" / name) != expected:
            raise AssertionError("Frozen operations source hash mismatch.")
    orders, scores, attributes, provenance = load_inputs(root)
    assert provenance == result["provenance"], "Underlying source/model/replay changed."
    candidates = pd.read_parquet(directory / "review_candidates.parquet")
    selected = pd.read_parquet(directory / "selected_orders.parquet")
    daily = pd.read_csv(directory / "daily_policy_results.csv")
    summaries = pd.read_csv(directory / "scenario_summary.csv")
    contrasts = pd.read_csv(directory / "statistical_contrasts.csv")
    # Recompute eligibility independently from the production batch builder.
    source = scores[["order_id", "approved_at"]].merge(orders[["order_id", "delivered_at"]], on="order_id", validate="one_to_one")
    cutoff = source["approved_at"].dt.floor("D") + pd.Timedelta(days=1, hours=9)
    known_complete = source["delivered_at"].notna() & (source["delivered_at"] < cutoff)
    assert set(candidates["order_id"]) == set(source.loc[~known_complete, "order_id"])
    assert candidates["order_id"].is_unique
    # Check all policies/scenarios directly, without the production verifier.
    decisions_checked = 0
    for summary in summaries.itertuples():
        for cutoff_value, batch in candidates.groupby("batch_cutoff"):
            ids = selected.loc[(selected["scenario"] == summary.scenario) & (selected["policy"] == summary.policy)
                               & (selected["batch_cutoff"] == cutoff_value), "order_id"]
            assert ids.is_unique and set(ids) <= set(batch["order_id"])
            chosen = batch.loc[batch["order_id"].isin(ids)]
            recomputed_cost = np.ceil(chosen["review_minutes"] * summary.cost_multiplier).sum()
            assert recomputed_cost <= summary.capacity_minutes
            assert len(chosen) <= protocol["planner"]["maximum_reviews_per_batch"]
            assert chosen.empty or chosen["primary_seller_id"].value_counts().max() <= protocol["planner"]["maximum_reviews_per_primary_seller"]
            decisions_checked += 1
        ids = selected.loc[(selected["scenario"] == summary.scenario) & (selected["policy"] == summary.policy), "order_id"]
        labels = scores.set_index("order_id").loc[ids, "observed_label_by_cutoff"]
        assert int(labels.isna().sum()) == summary.selected_unknown_outcomes
        assert int(labels.sum()) == summary.selected_known_late
        assert len(ids) == summary.selected_orders
    # A small real subset of every observed batch, under deliberately binding limits.
    subset_checks = []
    for cutoff_value, batch in candidates.groupby("batch_cutoff"):
        sample = batch.sort_values("order_id").head(10)
        limits = ReviewLimits(18, 4, 1)
        _, solver = optimize_reviews(sample, limits)
        expected = brute_force(sample, 18, 4, 1)
        assert solver["optimal"] and np.isclose(solver["priority_points"], expected, atol=1e-7)
        subset_checks.append({"batch_cutoff": str(cutoff_value), "orders": len(sample), "objective": expected})
    # Reconstruct each contrast directly in SQL and compare full-matrix OLS/CR1.
    expressions = {
        "distance": ("item_count>0 AND items_with_distance=item_count AND (max_distance_km<=500 OR max_distance_km>1000)", "cast(max_distance_km>1000 AS INTEGER)"),
        "basket": ("item_count>=1", "cast(item_count>=2 AS INTEGER)"),
        "promise": ("promised_calendar_days>=0", "cast(promised_calendar_days<=14 AS INTEGER)"),
        "interstate": ("item_count>0 AND states_known=item_count", "cast(interstate AS INTEGER)"),
    }
    statistic_checks = []
    with duckdb.connect(str(root / "data/interim/delivery_operations.duckdb"), read_only=True) as con:
        independent_total = con.execute("SELECT count(*),count(*) FILTER(WHERE sla_eligible),count(*) FILTER(WHERE is_late) FROM gold.orders").fetchone()
        assert independent_total == (result["statistics"]["source_orders"], result["statistics"]["eligible_orders"], result["statistics"]["late_orders"])
        for row in contrasts.itertuples():
            where, exposure = expressions[row.id]
            data = con.execute(f"""
                WITH movements AS (SELECT order_id,
                    count(*) FILTER(WHERE seller_state IS NOT NULL AND customer_state IS NOT NULL) states_known,
                    bool_or(seller_state<>customer_state) interstate
                    FROM gold.order_items GROUP BY order_id),
                base AS (SELECT o.*,m.states_known,m.interstate FROM gold.orders o LEFT JOIN movements m USING(order_id))
                SELECT purchased_at,cast(is_late AS INTEGER) is_late,{exposure} exposure
                FROM base WHERE sla_eligible AND ({where}) ORDER BY order_id
            """).df()
            assert len(data) == row.orders
            for value, prefix in [(0, "reference"), (1, "exposed")]:
                group = data.loc[data["exposure"] == value]
                assert len(group) == getattr(row, f"{prefix}_orders")
                assert int(group["is_late"].sum()) == getattr(row, f"{prefix}_late")
            # Full month dummy design independently confirms residualized estimator.
            months = pd.get_dummies(data["purchased_at"].dt.to_period("M"), dtype=float)
            design = np.column_stack([data["exposure"].to_numpy(), months.to_numpy()])
            coefficient = np.linalg.lstsq(design, data["is_late"].to_numpy(), rcond=None)[0]
            residual = data["is_late"].to_numpy() - design @ coefficient
            bread = np.linalg.inv(design.T @ design)
            dates = data["purchased_at"].dt.to_period("W-SUN")
            clustered = pd.DataFrame(design * residual[:, None]).groupby(dates.to_numpy()).sum().to_numpy()
            n, k = design.shape
            g = len(clustered)
            covariance = bread @ (clustered.T @ clustered) @ bread * g / (g - 1) * (n - 1) / (n - k)
            assert np.isclose(coefficient[0], row.adjusted_difference, atol=1e-12)
            assert np.isclose(np.sqrt(covariance[0, 0]), row.standard_error, atol=1e-12)
            assert month_adjusted_contrast(data)["clusters"] == row.clusters
            statistic_checks.append({"contrast": row.id, "sql_group_counts_match": True, "full_matrix_coefficient_and_cr1_match": True})
    # Aggregate unknowns remain unknown in every candidate, selected and summary count.
    all_labels = scores.set_index("order_id").loc[candidates["order_id"], "observed_label_by_cutoff"]
    assert int(all_labels.isna().sum()) == result["planning"]["candidate_unknown_outcomes"]
    suite = ET.parse(xml_path).getroot()
    testsuites = [suite] if suite.tag == "testsuite" else list(suite.findall("testsuite"))
    qa = {key: sum(int(s.attrib.get(key, 0)) for s in testsuites) for key in ["tests", "failures", "errors", "skipped"]}
    assert qa["tests"] > 40 and qa["failures"] == qa["errors"] == qa["skipped"] == 0
    qa["passed"] = qa["tests"]
    evidence = {"verified_at": datetime.now().astimezone().isoformat(), "run_id": result["run_id"],
                "source_and_frozen_code_hashes_match": True, "independent_screening_membership_match": True,
                "all_scenario_batch_policy_feasibility_checks": decisions_checked,
                "real_batch_subsets_exhaustively_checked": len(subset_checks), "subset_results": subset_checks,
                "independent_sql_and_full_matrix_statistical_checks": statistic_checks,
                "unknown_outcomes_preserved": True, "full_local_test_suite": qa,
                "all_optimized_batches_reported_optimal": result["planning"]["all_optimized_batches_optimal"],
                "production_qualified": False, "independent_new_period_validation": False}
    result["verification"] = evidence
    write_json(directory / "operations_results.json", result)
    write_json(root / "reports/operations/latest_completed.json", result)
    write_json(directory / "Verification.json", evidence)
    write_json(root / "docs/OPERATIONS_VERIFICATION.json", evidence)
    output.mkdir(parents=True, exist_ok=True)
    public_names = ["Operations_Results_Summary.md", "Verification.json", "statistical_contrasts.csv", "descriptive_groups.csv",
                    "scenario_summary.csv", "daily_policy_results.csv", "delivery_associations.png", "review_policy_comparison.png", "capacity_sensitivity.png"]
    for name in public_names:
        shutil.copy2(directory / name, output / name)
    (root / "docs/OPERATIONS_RESULTS.md").write_text((directory / "Operations_Results_Summary.md").read_text(encoding="utf-8"), encoding="utf-8")
    # Preserve the actual QA output beside the versioned run.
    shutil.copy2(xml_path, directory / "qa.xml")
    print(json.dumps({"run_id": result["run_id"], "passed": qa["passed"], "batch_policy_checks": decisions_checked,
                      "exhaustive_real_subsets": len(subset_checks), "output": str(output)}, indent=2))
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--qa-xml", type=Path, default=ROOT / "reports/operations/final_qa.xml")
    parser.add_argument("--output", type=Path, default=ROOT.parents[1] / "outputs/Delivery_Operations_Results")
    args = parser.parse_args()
    verify(args.root.resolve(), args.qa_xml.resolve(), args.output.resolve())
