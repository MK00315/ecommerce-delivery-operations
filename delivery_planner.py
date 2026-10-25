"""Outcome-blind, constrained review-priority simulation using scipy/HiGHS."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_array, vstack


DECISION_COLUMNS = ["order_id", "approved_at", "batch_cutoff", "primary_seller_id", "priority_points", "review_minutes"]


@dataclass(frozen=True)
class ReviewLimits:
    minutes: int = 120
    maximum_reviews: int = 30
    per_primary_seller: int = 5
    solver_seconds: float = 10.0

    def validate(self):
        for value in [self.minutes, self.maximum_reviews, self.per_primary_seller]:
            if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 0:
                raise ValueError("Capacity limits must be nonnegative integers.")
        if not np.isfinite(self.solver_seconds) or self.solver_seconds <= 0:
            raise ValueError("The solver time limit must be positive and finite.")


def validate_candidates(candidates):
    """Strict allowlist keeps labels, final statuses and future events out of solver."""
    if set(candidates.columns) != set(DECISION_COLUMNS):
        raise ValueError("Planner accepts only the outcome-blind decision columns.")
    if candidates.isna().any().any() or not candidates["order_id"].is_unique:
        raise ValueError("Candidates need unique IDs and no missing decision fields.")
    if not candidates.empty and candidates["batch_cutoff"].nunique() != 1:
        raise ValueError("Optimize one batch at a time.")
    if not (candidates["approved_at"] < candidates["batch_cutoff"]).all():
        raise ValueError("Every approval must precede the batch cutoff.")
    for column in ["priority_points", "review_minutes"]:
        values = candidates[column].to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError("Priority and review minutes must be finite and positive.")
    if not np.equal(candidates["review_minutes"], np.ceil(candidates["review_minutes"])).all():
        raise ValueError("Review minutes must be whole numbers.")


def verify_selection(candidates, selected_ids, limits):
    limits.validate()
    validate_candidates(candidates)
    selected_ids = list(selected_ids)
    if len(selected_ids) != len(set(selected_ids)) or not set(selected_ids) <= set(candidates["order_id"]):
        raise ValueError("A selection contains duplicate or unknown orders.")
    selected = candidates.loc[candidates["order_id"].isin(selected_ids)]
    if len(selected) > limits.maximum_reviews or selected["review_minutes"].sum() > limits.minutes:
        raise ValueError("Selected work exceeds the count or time budget.")
    if not selected.empty and selected.groupby("primary_seller_id").size().max() > limits.per_primary_seller:
        raise ValueError("Selected work exceeds a primary-seller limit.")
    return {"selected_orders": len(selected), "used_minutes": int(selected["review_minutes"].sum()),
            "priority_points": float(selected["priority_points"].sum()),
            "unused_minutes": int(limits.minutes - selected["review_minutes"].sum())}


def greedy_selection(candidates, limits, policy):
    limits.validate()
    validate_candidates(candidates)
    data = candidates.copy()
    if policy == "risk_first":
        data = data.sort_values(["priority_points", "order_id"], ascending=[False, True])
    elif policy == "priority_per_minute":
        data["ratio"] = data["priority_points"] / data["review_minutes"]
        data = data.sort_values(["ratio", "priority_points", "order_id"], ascending=[False, False, True])
    elif policy == "oldest_first":
        data = data.sort_values(["approved_at", "order_id"])
    else:
        raise ValueError("Unknown review policy.")
    selected, used, sellers = [], 0, {}
    for row in data.itertuples():
        if len(selected) >= limits.maximum_reviews:
            break
        if used + row.review_minutes <= limits.minutes and sellers.get(row.primary_seller_id, 0) < limits.per_primary_seller:
            selected.append(row.order_id)
            used += row.review_minutes
            sellers[row.primary_seller_id] = sellers.get(row.primary_seller_id, 0) + 1
    return selected, verify_selection(candidates, selected, limits)


def optimize_reviews(candidates, limits):
    limits.validate()
    validate_candidates(candidates)
    data = candidates.sort_values("order_id").reset_index(drop=True)
    if data.empty or min(limits.minutes, limits.maximum_reviews, limits.per_primary_seller) == 0:
        return [], {**verify_selection(data, [], limits), "status": "optimal_empty", "optimal": True, "solver_gap": 0.0}
    seller_codes, sellers = pd.factorize(data["primary_seller_id"], sort=True)
    n = len(data)
    seller_matrix = csc_array((np.ones(n), (seller_codes, np.arange(n))), shape=(len(sellers), n))
    matrix = vstack([csc_array(data["review_minutes"].to_numpy(dtype=float).reshape(1, -1)),
                     csc_array(np.ones((1, n))), seller_matrix], format="csc")
    upper = np.r_[limits.minutes, limits.maximum_reviews, np.full(len(sellers), limits.per_primary_seller)]
    result = milp(-data["priority_points"].to_numpy(dtype=float), integrality=np.ones(n), bounds=Bounds(0, 1),
                  constraints=LinearConstraint(matrix, np.full(len(upper), -np.inf), upper),
                  options={"time_limit": limits.solver_seconds, "mip_rel_gap": 0.0})
    # A time-limited incumbent is useful but must never be called an optimum.
    if result.x is None or result.status not in {0, 1} or np.max(np.abs(result.x - np.round(result.x))) > 1e-5:
        raise RuntimeError(f"Solver did not produce a feasible integer solution: {result.message}")
    selected = data.loc[result.x > 0.5, "order_id"].tolist()
    info = verify_selection(data, selected, limits)
    return selected, {**info, "status": str(result.message), "optimal": bool(result.status == 0),
                      "solver_gap": float(result.mip_gap), "nodes": int(result.mip_node_count)}


def prepare_review_batches(scores, attributes, assumptions, multiplier=1.0):
    """Eligibility sees only a completion already observed at the screening time.

    Future delivery timestamps have no role in score, minutes or selection. Final
    source statuses and labels are not accepted here. Global replay ranks are ignored.
    """
    if not np.isfinite(multiplier) or multiplier <= 0:
        raise ValueError("The review-time multiplier must be positive and finite.")
    required_scores = {"order_id", "approved_at", "raw_model_score"}
    required_attributes = {"order_id", "item_count", "seller_count", "primary_seller_id", "known_interstate_share", "delivered_at"}
    if set(scores.columns) != required_scores or set(attributes.columns) != required_attributes:
        raise ValueError("Batch preparation requires explicit score and snapshot fields only.")
    if scores.isna().any().any() or not np.isfinite(scores["raw_model_score"]).all():
        raise ValueError("Scores must have known approvals and finite values.")
    if not scores["order_id"].is_unique or not attributes["order_id"].is_unique:
        raise ValueError("One score and snapshot per order is required.")
    data = scores.merge(attributes, on="order_id", how="left", validate="one_to_one", indicator=True)
    if not data["_merge"].eq("both").all() or data[["item_count", "seller_count", "primary_seller_id"]].isna().any().any():
        raise ValueError("Every score must have a complete basket snapshot and primary seller.")
    data["batch_cutoff"] = data["approved_at"].dt.normalize() + pd.Timedelta(days=1, hours=9)
    known_complete = data["delivered_at"].notna() & (data["delivered_at"] < data["batch_cutoff"])
    audit = {"scored_approvals": len(data), "already_delivered_before_screening": int(known_complete.sum())}
    data = data.loc[~known_complete].copy()
    audit["candidate_orders"] = len(data)
    costs = assumptions["review_minutes"]
    minutes = (costs["base"] + (data["item_count"] > 1) * costs["multiple_items_extra"]
               + (data["seller_count"] > 1) * costs["multiple_sellers_extra"]
               + (data["known_interstate_share"].isna() | (data["known_interstate_share"] > 0)) * costs["interstate_or_unknown_extra"])
    data["review_minutes"] = np.ceil(minutes * multiplier).astype(int)
    data = data.sort_values(["batch_cutoff", "raw_model_score", "order_id"], ascending=[True, False, True])
    rank = data.groupby("batch_cutoff").cumcount() + 1
    size = data.groupby("batch_cutoff")["order_id"].transform("size")
    data["priority_points"] = 100.0 * (size - rank + 1) / size
    candidates = data[DECISION_COLUMNS].reset_index(drop=True)
    for _, batch in candidates.groupby("batch_cutoff"):
        validate_candidates(batch)
    return candidates, audit


def evaluate_selected(candidates, selected_ids, outcomes):
    """Retrospective scoring only: this function is never used to select orders."""
    if not outcomes["order_id"].is_unique or not outcomes["observed_label_by_cutoff"].dropna().isin([0, 1]).all():
        raise ValueError("Outcomes must have unique IDs and nullable binary labels.")
    data = candidates[["order_id"]].merge(outcomes[["order_id", "observed_label_by_cutoff"]], on="order_id", how="left", validate="one_to_one", indicator=True)
    if not data["_merge"].eq("both").all():
        raise ValueError("Every candidate must be represented in the nullable outcome ledger.")
    selected_ids = list(selected_ids)
    if len(selected_ids) != len(set(selected_ids)) or not set(selected_ids) <= set(candidates["order_id"]):
        raise ValueError("Cannot evaluate duplicate or unknown selections.")
    labels = data["observed_label_by_cutoff"]
    reviewed = data.loc[data["order_id"].isin(selected_ids), "observed_label_by_cutoff"]
    total_late, captured = int(labels.sum()), int(reviewed.sum())
    return {"candidate_orders": len(data), "candidate_known_outcomes": int(labels.notna().sum()),
            "candidate_unknown_outcomes": int(labels.isna().sum()), "candidate_known_late": total_late,
            "selected_orders": len(reviewed), "selected_known_outcomes": int(reviewed.notna().sum()),
            "selected_unknown_outcomes": int(reviewed.isna().sum()), "selected_known_late": captured,
            "known_late_capture": captured / total_late if total_late else None,
            "observed_late_fraction_among_known_reviews": captured / int(reviewed.notna().sum()) if reviewed.notna().any() else None}
