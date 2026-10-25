"""Run local statistics and outcome-blind review-planning scenarios; retain evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from delivery_pipeline import sha256, write_json
from delivery_planner import (DECISION_COLUMNS, ReviewLimits, evaluate_selected, greedy_selection,
                              optimize_reviews, prepare_review_batches)
from delivery_statistics import analyse_contrasts, descriptive_groups

ROOT = Path(__file__).resolve().parent
PALETTE = {"optimized": "#0284c7", "risk_first": "#38bdf8", "priority_per_minute": "#0f766e", "oldest_first": "#64748b"}
POLICY_NAMES = {"optimized": "Constrained optimizer", "risk_first": "Highest risk first",
                "priority_per_minute": "Priority per minute", "oldest_first": "Oldest approval first"}


def load_inputs(root):
    model = json.loads((root / "models/latest_model.json").read_text())
    study = json.loads((root / model["report"]).read_text())
    score_path = root / study["artifacts"]["august_replay_scores"]
    if sha256(root / model["model"]) != model["model_sha256"]:
        raise ValueError("The saved model does not match its verified pointer.")
    scores = pd.read_parquet(score_path).reset_index()
    if scores["model_run_id"].nunique() != 1 or scores["model_run_id"].iloc[0] != model["run_id"]:
        raise ValueError("Replay/model provenance mismatch.")
    if not scores["observed_label_by_cutoff"].notna().eq(scores["outcome_evaluable"]).all():
        raise ValueError("Unknown replay outcomes were incorrectly represented.")
    with duckdb.connect(str(root / "data/interim/delivery_operations.duckdb"), read_only=True) as connection:
        orders = connection.execute("""
            WITH states AS (
                SELECT order_id, count(*) FILTER(WHERE seller_state IS NOT NULL AND customer_state IS NOT NULL) items_with_state,
                       bool_or(seller_state<>customer_state) any_interstate,
                       avg(CASE WHEN seller_state IS NOT NULL AND customer_state IS NOT NULL
                           THEN cast(seller_state<>customer_state AS DOUBLE) END) known_interstate_share
                FROM gold.order_items GROUP BY order_id
            ), primary_seller AS (
                SELECT order_id,seller_id primary_seller_id,
                       row_number() OVER(PARTITION BY order_id ORDER BY count(*) DESC,seller_id) rn
                FROM gold.order_items GROUP BY order_id,seller_id
            )
            SELECT o.*,s.* EXCLUDE(order_id),p.primary_seller_id
            FROM gold.orders o LEFT JOIN states s USING(order_id)
            LEFT JOIN primary_seller p ON o.order_id=p.order_id AND p.rn=1
            ORDER BY o.order_id
        """).df()
    if not orders["order_id"].is_unique or not scores["order_id"].is_unique:
        raise ValueError("Source and replay must both be at order grain.")
    check = scores[["order_id", "approved_at"]].merge(orders[["order_id", "approved_at"]],
        on="order_id", how="left", suffixes=("_score", "_source"), validate="one_to_one")
    if not check["approved_at_score"].eq(check["approved_at_source"]).all():
        raise ValueError("Every score must reconcile with its source approval.")
    attributes = orders[["order_id", "item_count", "seller_count", "primary_seller_id", "known_interstate_share", "delivered_at"]].copy()
    attributes.loc[orders["items_with_state"] != orders["item_count"], "known_interstate_share"] = np.nan
    provenance = {"database_sha256": sha256(root / "data/interim/delivery_operations.duckdb"),
                  "replay_sha256": sha256(score_path), "replay_path": score_path.relative_to(root).as_posix(),
                  "model_run_id": model["run_id"], "model_sha256": model["model_sha256"],
                  "raw_manifest_sha256": sha256(root / "docs/raw_dataset_manifest.json"),
                  "model_production_qualified": model["production_qualified"],
                  "evaluation_role": "Reused August diagnostic; no independent new-period validation"}
    return orders, scores, attributes, provenance


def run_scenario(candidates, outcomes, assumptions, minutes, multiplier, scenario_id):
    limits = ReviewLimits(minutes, assumptions["maximum_reviews_per_batch"],
                          assumptions["maximum_reviews_per_primary_seller"], assumptions["solver_seconds_per_batch"])
    daily, selected = [], []
    for cutoff, batch in candidates.groupby("batch_cutoff", sort=True):
        policies = [("optimized", *optimize_reviews(batch, limits))]
        policies += [(name, *greedy_selection(batch, limits, name)) for name in assumptions["baselines"]]
        best_greedy = max(info["priority_points"] for name, _, info in policies if name != "optimized")
        if policies[0][2]["optimal"] and policies[0][2]["priority_points"] + 1e-6 < best_greedy:
            raise AssertionError("Claimed optimizer objective is lower than a feasible baseline.")
        for policy, ids, info in policies:
            row = {"scenario": scenario_id, "policy": policy, "batch_cutoff": cutoff,
                   "capacity_minutes": minutes, "cost_multiplier": multiplier, **info,
                   **evaluate_selected(batch, ids, outcomes)}
            daily.append(row)
            selected.extend({"scenario": scenario_id, "policy": policy, "batch_cutoff": cutoff, "order_id": value} for value in ids)
    daily = pd.DataFrame(daily)
    selected = pd.DataFrame(selected, columns=["scenario", "policy", "batch_cutoff", "order_id"])
    aggregates = []
    for policy, rows in daily.groupby("policy", sort=False):
        ids = selected.loc[selected["policy"] == policy, "order_id"].tolist()
        aggregate = {"scenario": scenario_id, "policy": policy, "capacity_minutes": minutes,
                     "cost_multiplier": multiplier, "batches": int(len(rows)),
                     "used_minutes": int(rows["used_minutes"].sum()),
                     "unused_minutes": int(rows["unused_minutes"].sum()),
                     "priority_points": float(rows["priority_points"].sum()),
                     "all_batches_optimal": bool(rows["optimal"].fillna(False).all()) if policy == "optimized" else None,
                     **evaluate_selected(candidates, ids, outcomes)}
        aggregates.append(aggregate)
    return daily, selected, pd.DataFrame(aggregates)


def make_figures(directory, contrasts, summary):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "figure.facecolor": "white"})
    fig, ax = plt.subplots(figsize=(10, 5.0))
    y = np.arange(len(contrasts))
    estimate = contrasts["adjusted_difference"].to_numpy() * 100
    lower, upper = contrasts["ci_low"].to_numpy() * 100, contrasts["ci_high"].to_numpy() * 100
    ax.errorbar(estimate, y, xerr=np.vstack([estimate - lower, upper - estimate]), fmt="o", color="#0284c7", capsize=5)
    ax.axvline(0, color="#94a3b8", lw=1)
    ax.set_yticks(y, contrasts["label"])
    ax.invert_yaxis()
    ax.set_xlabel("Difference in late rate (percentage points)")
    ax.set_title("Historical delivery associations", loc="left", pad=18)
    ax.grid(axis="x", color="#e2e8f0")
    fig.text(0.015, 0.015, "Purchase-month adjustment; purchase-week clustered 95% intervals. Exploratory associations, not causal effects.\nIntervals are marginal; Holm correction applies to the four reported p-values.", fontsize=8, color="#475569")
    fig.tight_layout(rect=(0, 0.10, 1, 1))
    fig.savefig(directory / "delivery_associations.png", dpi=180, bbox_inches="tight", pad_inches=0.22)
    plt.close(fig)

    base = summary.loc[(summary["cost_multiplier"] == 1.0) & (summary["capacity_minutes"] == 120)]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.9))
    positions = np.arange(len(base))
    labels = [POLICY_NAMES[p].replace(" ", "\n", 1) for p in base["policy"]]
    colors = [PALETTE[p] for p in base["policy"]]
    for ax, column, title in [(axes[0], "selected_orders", "Orders offered human review"),
                              (axes[1], "selected_known_late", "Known late orders in the queue")]:
        bars = ax.bar(positions, base[column], color=colors, width=0.65)
        ax.set_xticks(positions, labels, fontsize=8)
        ax.set_title(title, fontsize=12, loc="left", pad=15)
        ax.bar_label(bars, padding=4, fontsize=9)
        ax.set_ylim(0, max(base[column].max() * 1.18, 1))
        ax.grid(axis="y", color="#e2e8f0", zorder=0)
        ax.set_axisbelow(True)
    fig.suptitle("August 2018 review simulation | 120 pooled minutes per batch", x=0.04, ha="left", fontweight="bold", fontsize=13)
    fig.text(0.02, 0.015, "Same time, count and primary-seller caps for every policy. Illustrative review times.\nKnown late counts are retrospective diagnostics, not prevented delays; unknown outcomes still consume review time.", fontsize=8, color="#475569")
    fig.tight_layout(rect=(0, 0.11, 1, 0.94))
    fig.savefig(directory / "review_policy_comparison.png", dpi=180, bbox_inches="tight", pad_inches=0.22)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.9))
    sensitivity = summary.loc[summary["cost_multiplier"] == 1.0]
    for policy, rows in sensitivity.groupby("policy", sort=False):
        rows = rows.sort_values("capacity_minutes")
        for ax, column in [(axes[0], "selected_orders"), (axes[1], "priority_points")]:
            ax.plot(rows["capacity_minutes"], rows[column], "o-", color=PALETTE[policy], label=POLICY_NAMES[policy], lw=1.7, markersize=4)
            ax.set_xlabel("Pooled review minutes per batch")
            ax.grid(color="#e2e8f0")
    axes[0].set_title("Review volume across all batches", loc="left", fontsize=12)
    axes[1].set_title("Ordinal priority points allocated", loc="left", fontsize=12)
    axes[1].legend(fontsize=8, loc="lower right")
    fig.suptitle("Capacity sensitivity | August 2018 reused diagnostic", x=0.04, ha="left", fontweight="bold", fontsize=13)
    fig.text(0.02, 0.015, "30-review and 5-per-primary-seller caps remain fixed, so extra minutes can stop adding reviews.\nPriority points are a scenario objective, not expected delays or financial benefit.", fontsize=8, color="#475569")
    fig.tight_layout(rect=(0, 0.10, 1, 0.94))
    fig.savefig(directory / "capacity_sensitivity.png", dpi=180, bbox_inches="tight", pad_inches=0.22)
    plt.close(fig)


def write_report(directory, result, contrasts, scenarios):
    stat, plan = result["statistics"], result["planning"]
    text = ["# Delivery statistics and review-capacity planning", "",
            "Executed locally on the laptop with Python. This report uses historical public Olist data, not live delivery operations.", "",
            "## Historical patterns", "",
            f"The source has {stat['source_orders']:,} orders. Analysis uses {stat['eligible_orders']:,} eligible completed orders, including {stat['late_orders']:,} late orders ({stat['late_rate']:.2%}). The other {stat['ineligible_orders']:,} orders are outside that outcome denominator.", "",
            "Each contrast includes purchase-month fixed effects. Uncertainty clusters orders by purchase week; a day-cluster sensitivity is also saved. Differences are in percentage points (pp). These are separate observational contrasts, with no claim that changing an input would cause the reported change.", "",
            "| Comparison | Reference late rate | Exposed late rate | Month-adjusted difference (95% interval) | Holm p | Contrast exclusions |",
            "|---|---:|---:|---:|---:|---:|"]
    for row in contrasts.itertuples():
        text.append(f"| {row.label} | {row.reference_rate:.2%} ({row.reference_orders:,}) | {row.exposed_rate:.2%} ({row.exposed_orders:,}) | {row.adjusted_difference*100:+.2f} pp ({row.ci_low*100:+.2f}, {row.ci_high*100:+.2f}) | {row.holm_p_value:.3g} | {row.excluded_from_contrast:,} |")
    text += ["", "The four two-sided primary p-values use Holm family-wise correction. Displayed 95% intervals are marginal, not simultaneous. Thresholds were fixed for this exploratory analysis after earlier data inspection, not preregistered. Week-cluster inference assumes independence across weeks and does not fully account for recurring sellers/customers or longer dependence. Purchase-month adjustment does not eliminate confounding, censoring, selection into completed delivery or snapshot-availability assumptions.", "",
             "## Review-capacity scenario", "",
             f"The saved model scores cover {plan['scored_approvals']:,} valid August approvals. At 09:00 the next day, {plan['already_delivered_before_screening']:,} orders already have a recorded completed delivery and leave the queue. The remaining {plan['candidate_orders']:,} orders form {plan['batches']} once-only daily screening batches. Their outcomes are joined only after selection. {plan['candidate_unknown_outcomes']:,} candidate outcomes remain unknown.", "",
             "The default assumption is **120 pooled team minutes per batch**, at most **30 reviews** and **5 reviews per primary seller**. A basket takes 4 assumed minutes, plus 2 for multiple items, 3 for multiple sellers and 1 for any interstate/unknown-state movement. These durations are scenario assumptions, not measured staffing data. The primary seller is the most frequent item seller, with seller ID breaking ties; the concentration limit does not cover every seller of a mixed basket.", "",
             "All approvals are known before the screening cutoff. Only delivery completion recorded before that cutoff can affect eligibility. The solver cannot receive outcomes, final statuses or future timestamps. Within-batch score rank becomes 0-100 ordinal priority points; the full-August percentile is ignored. The optimizer maximizes total points subject to the declared constraints. Points have no probability, avoided-delay or monetary interpretation. Staff minutes are pooled; this is not individual shift scheduling or fleet routing. Unselected orders are not carried over.", "",
             "| Default policy | Reviewed | Minutes used across all batches | Unknown outcomes reviewed | Known late orders reviewed | Capture of known candidate late orders | Priority points |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    base = scenarios.loc[scenarios["scenario"] == "capacity_120_cost_1"]
    for row in base.itertuples():
        text.append(f"| {POLICY_NAMES[row.policy]} | {row.selected_orders:,} | {row.used_minutes:,} | {row.selected_unknown_outcomes:,} | {row.selected_known_late:,} | {row.known_late_capture:.2%} | {row.priority_points:,.1f} |")
    optimized = base.loc[base["policy"] == "optimized"].iloc[0]
    risk = base.loc[base["policy"] == "risk_first"].iloc[0]
    text += ["", f"The optimizer's objective is ordinal priority allocation, not maximizing known historical late counts. It reviews {int(optimized['selected_orders'])} orders and encounters {int(optimized['selected_known_late'])} known late outcomes; highest-risk-first encounters {int(risk['selected_known_late'])}. Actual late counts can differ from the score objective. No policy is selected or tuned using these retrospective outcomes.", "",
             "Sensitivity covers 0, 60, 120, 180 and 240 minutes per batch and 0.75x/1x/1.25x duration assumptions (rounded up to whole minutes). Every baseline uses the same limits. Optimization status/gap is recorded per batch; a time-limited feasible solution is never labelled optimal. No budget violation is accepted.", "",
             "The original model failed its first independent August test. The updated model and this planner reuse August as a diagnostic. Absolute model probabilities are unreliable and ranking gains modest. This replay is not independent new-period validation, evidence of causal impact, prevented delays, savings or a production-ready decision system.", "",
             "## Files and verification", "",
             "- `statistical_contrasts.csv`: group counts, rates, adjusted differences, week/day intervals and Holm p-values.",
             "- `descriptive_groups.csv`: complete partitions by state, distance, basket, promise and purchase month; small groups flagged.",
             "- `scenario_summary.csv` / `daily_policy_results.csv`: all policies, capacities, time assumptions and solver status.",
             "- Private versioned run: `review_candidates.parquet`, `selected_orders.parquet`, archived protocol/code and source hashes. These order-level outputs remain excluded from Git.",
             "- `Verification.json`: independent reconciliations and tests, produced after the run.", "",
             "Methods: [SciPy mixed-integer solver](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html), [CR1 clustered covariance reference](https://www.statsmodels.org/stable/generated/statsmodels.stats.sandwich_covariance.cov_cluster.html), [Holm correction reference](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html). CR1/FWL and Holm are implemented with NumPy/SciPy; the statsmodels package is not required.", "",
             f"Run: `{result['run_id']}`. Source/model hashes and the frozen protocol are retained in the run manifest.", ""]
    (directory / "Operations_Results_Summary.md").write_text("\n".join(text), encoding="utf-8")


def main(root=ROOT):
    started = time.perf_counter()
    protocol_path = root / "operations_protocol.json"
    protocol = json.loads(protocol_path.read_text())
    # This code implements these four contrasts explicitly; changing the protocol
    # must not silently change the multiple-testing family or documented objective.
    if [h["id"] for h in protocol["statistics"]["hypotheses"]] != ["distance", "basket", "promise", "interstate"]:
        raise ValueError("Unexpected statistical family.")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = root / "reports/operations" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    snapshot = directory / "source_snapshot"
    snapshot.mkdir()
    source_files = ["operations_protocol.json", "delivery_statistics.py", "delivery_planner.py", "run_delivery_operations.py",
                    "verify_delivery_operations.py", "tests/test_operations.py"]
    source_hashes = {}
    for name in source_files:
        path = root / name
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        source_hashes[name] = sha256(target)
    shutil.copy2(protocol_path, directory / "protocol.json")
    orders, scores, attributes, provenance = load_inputs(root)
    eligible = orders.loc[orders["sla_eligible"].eq(True)].copy()
    contrasts = analyse_contrasts(eligible, protocol["statistics"]["hypotheses"])
    groups = descriptive_groups(eligible)
    contrasts.to_csv(directory / "statistical_contrasts.csv", index=False)
    groups.to_csv(directory / "descriptive_groups.csv", index=False)
    print(f"Statistics completed: {len(eligible):,} eligible orders; four contrasts.", flush=True)
    outcomes = scores[["order_id", "observed_label_by_cutoff"]]
    score_inputs = scores[["order_id", "approved_at", "raw_model_score"]]
    settings = protocol["planner"]
    all_daily, all_selected, all_summaries = [], [], []
    candidates_default = None
    scenarios = [(v, 1.0) for v in settings["sensitivity_capacity_minutes"]]
    scenarios += [(settings["capacity_minutes_per_batch"], v) for v in settings["sensitivity_cost_multipliers"] if v != 1.0]
    for minutes, multiplier in scenarios:
        candidates, audit = prepare_review_batches(score_inputs, attributes, settings, multiplier)
        if minutes == settings["capacity_minutes_per_batch"] and multiplier == 1.0:
            candidates_default = candidates
            default_audit = audit
        scenario_id = f"capacity_{minutes}_cost_{multiplier:g}"
        daily, selected, summary = run_scenario(candidates, outcomes, settings, minutes, multiplier, scenario_id)
        all_daily.append(daily)
        all_selected.append(selected)
        all_summaries.append(summary)
        print(f"Completed {scenario_id}: {len(daily) // 4} batches, four policies.", flush=True)
    if candidates_default is None:
        raise AssertionError("The default scenario must be included in the sensitivity grid.")
    daily = pd.concat(all_daily, ignore_index=True)
    selected = pd.concat(all_selected, ignore_index=True)
    summary = pd.concat(all_summaries, ignore_index=True)
    candidates_default.to_parquet(directory / "review_candidates.parquet", index=False)
    selected.to_parquet(directory / "selected_orders.parquet", index=False)
    daily.to_csv(directory / "daily_policy_results.csv", index=False)
    summary.to_csv(directory / "scenario_summary.csv", index=False)
    plan_counts = evaluate_selected(candidates_default, [], outcomes)
    result = {"run_id": run_id, "version": protocol["version"], "executed_at": datetime.now().astimezone().isoformat(),
              "execution": "Local laptop CPU; no cloud compute, retraining or deployment",
              "provenance": provenance, "source_code_sha256": source_hashes,
              "statistics": {"source_orders": len(orders), "eligible_orders": len(eligible),
                             "ineligible_orders": len(orders) - len(eligible), "late_orders": int(eligible["is_late"].sum()),
                             "late_rate": float(eligible["is_late"].mean()), "hypotheses": 4,
                             "associational_only": True, "results": contrasts.to_dict(orient="records")},
              "planning": {**default_audit, "batches": int(candidates_default["batch_cutoff"].nunique()),
                           "candidate_known_late": plan_counts["candidate_known_late"],
                           "candidate_unknown_outcomes": plan_counts["candidate_unknown_outcomes"],
                           "scenarios": len(scenarios), "policies": 4,
                           "all_optimized_batches_optimal": bool(summary.loc[summary["policy"] == "optimized", "all_batches_optimal"].all()),
                           "summary": json.loads(summary.to_json(orient="records", double_precision=15))},
              "protocol": protocol, "report_directory": directory.relative_to(root).as_posix(),
              "elapsed_seconds": round(time.perf_counter() - started, 2),
              "verification": "Execution complete; independent verification and final test suite pending"}
    make_figures(directory, contrasts, summary)
    write_report(directory, result, contrasts, summary)
    # Guard against accidental mutation of source data or model during execution.
    if sha256(root / "data/interim/delivery_operations.duckdb") != provenance["database_sha256"]:
        raise AssertionError("The read-only source database changed during operations analysis.")
    write_json(directory / "operations_results.json", result)
    write_json(root / "reports/operations/latest_completed.json", result)
    print(f"Operations run saved: {run_id}", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    arguments = parser.parse_args()
    with threadpool_limits(limits=4):
        main(arguments.root.resolve())
