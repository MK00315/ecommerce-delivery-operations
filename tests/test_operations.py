"""Inference, time availability, missing outcomes and independent solver checks."""
import itertools
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_planner import (DECISION_COLUMNS, ReviewLimits, evaluate_selected, greedy_selection,
                              optimize_reviews, prepare_review_batches, verify_selection)
from delivery_statistics import contrast_exposure, holm_adjust, month_adjusted_contrast


def small_batch(points=(10, 9, 9), minutes=(6, 5, 5), sellers=("a", "b", "c")):
    return pd.DataFrame({"order_id": [f"order-{i}" for i in range(len(points))],
                         "approved_at": pd.Timestamp("2018-08-01 10:00"),
                         "batch_cutoff": pd.Timestamp("2018-08-02 09:00"),
                         "primary_seller_id": sellers, "priority_points": points, "review_minutes": minutes})


def exhaustive_value(batch, limits):
    """Independent enumeration, not the production feasibility checker."""
    best = 0.0
    for flags in itertools.product([False, True], repeat=len(batch)):
        chosen = batch.loc[list(flags)]
        if len(chosen) > limits.maximum_reviews or chosen["review_minutes"].sum() > limits.minutes:
            continue
        if not chosen.empty and chosen["primary_seller_id"].value_counts().max() > limits.per_primary_seller:
            continue
        best = max(best, float(chosen["priority_points"].sum()))
    return best


def test_optimizer_improves_over_highest_score_greedy_under_unequal_minutes():
    batch = small_batch()
    limits = ReviewLimits(10, 3, 3)
    _, greedy = greedy_selection(batch, limits, "risk_first")
    ids, result = optimize_reviews(batch, limits)
    assert result["optimal"] and set(ids) == {"order-1", "order-2"}
    assert result["priority_points"] == 18 > greedy["priority_points"] == 10


@pytest.mark.parametrize("seed", [4, 9, 17])
def test_optimizer_matches_exhaustive_feasible_subsets_with_binding_seller_and_count_caps(seed):
    rng = np.random.default_rng(seed)
    batch = small_batch(tuple(rng.integers(1, 100, 8)), tuple(rng.integers(2, 9, 8)), tuple(rng.choice(["a", "b", "c"], 8)))
    limits = ReviewLimits(17, 4, 2)
    _, result = optimize_reviews(batch, limits)
    assert result["optimal"]
    assert result["priority_points"] == pytest.approx(exhaustive_value(batch, limits))


@pytest.mark.parametrize("limits", [ReviewLimits(0, 10, 5), ReviewLimits(100, 0, 5), ReviewLimits(100, 10, 0)])
def test_zero_capacity_or_limits_cannot_select_any_work(limits):
    ids, result = optimize_reviews(small_batch(), limits)
    assert ids == [] and result["used_minutes"] == 0 and result["optimal"]


def test_primary_seller_cap_cannot_be_evaded_by_order_count_or_free_capacity():
    batch = small_batch(sellers=("same", "same", "other"))
    _, result = optimize_reviews(batch, ReviewLimits(100, 10, 1))
    assert result["selected_orders"] == 2 and result["priority_points"] == 19


def test_solver_rejects_outcome_columns_and_budget_violations():
    batch = small_batch()
    with pytest.raises(ValueError, match="outcome-blind"):
        optimize_reviews(batch.assign(is_late=[1, 0, 1]), ReviewLimits())
    with pytest.raises(ValueError, match="time budget"):
        verify_selection(batch, batch["order_id"], ReviewLimits(1, 30, 5))


@pytest.mark.parametrize("problem", ["nan_score", "negative_cost", "fractional_cost", "future_approval", "duplicate_id"])
def test_invalid_candidates_are_rejected(problem):
    batch = small_batch()
    if problem == "nan_score":
        batch.loc[0, "priority_points"] = np.nan
    elif problem == "negative_cost":
        batch.loc[0, "review_minutes"] = -1
    elif problem == "fractional_cost":
        batch["review_minutes"] = batch["review_minutes"].astype(float)
        batch.loc[0, "review_minutes"] = 4.5
    elif problem == "future_approval":
        batch.loc[0, "approved_at"] = batch.loc[0, "batch_cutoff"]
    elif problem == "duplicate_id":
        batch.loc[1, "order_id"] = batch.loc[0, "order_id"]
    with pytest.raises(ValueError):
        optimize_reviews(batch, ReviewLimits())


def snapshot_fixture():
    scores = pd.DataFrame({"order_id": ["a", "b", "c", "d"], "approved_at": pd.Timestamp("2018-08-01 10:00"),
                           "raw_model_score": [0.4, 0.7, 0.7, 0.2]})
    attributes = pd.DataFrame({"order_id": ["a", "b", "c", "d"], "item_count": [1, 2, 2, 1],
                               "seller_count": [1, 1, 2, 1], "primary_seller_id": ["s1", "s2", "s3", "s4"],
                               "known_interstate_share": [0, 1, 1, np.nan],
                               "delivered_at": pd.to_datetime(["2018-08-02 08:00", "2018-08-10", "2018-08-12", None], format="ISO8601")})
    assumptions = {"review_minutes": {"base": 4, "multiple_items_extra": 2,
                                      "multiple_sellers_extra": 3, "interstate_or_unknown_extra": 1}}
    return scores, attributes, assumptions


def test_screening_removes_only_completion_known_before_cutoff_and_uses_daily_ranks():
    scores, attributes, assumptions = snapshot_fixture()
    candidates, audit = prepare_review_batches(scores, attributes, assumptions)
    assert audit == {"scored_approvals": 4, "already_delivered_before_screening": 1, "candidate_orders": 3}
    assert candidates["order_id"].tolist() == ["b", "c", "d"]
    assert candidates["priority_points"].tolist() == pytest.approx([100, 200 / 3, 100 / 3])
    assert candidates["review_minutes"].tolist() == [7, 10, 5]
    assert candidates.columns.tolist() == DECISION_COLUMNS


def test_future_delivery_changes_cannot_change_selection_or_batch_priority():
    scores, attributes, assumptions = snapshot_fixture()
    original, _ = prepare_review_batches(scores, attributes, assumptions)
    attributes.loc[1:2, "delivered_at"] = pd.Timestamp("2019-01-01")
    changed, _ = prepare_review_batches(scores, attributes, assumptions)
    pd.testing.assert_frame_equal(original, changed)
    assert optimize_reviews(original, ReviewLimits(15, 30, 5))[0] == optimize_reviews(changed, ReviewLimits(15, 30, 5))[0]


def test_appending_future_batch_cannot_change_earlier_rank_or_review_cost():
    scores, attributes, assumptions = snapshot_fixture()
    original, _ = prepare_review_batches(scores, attributes, assumptions)
    scores.loc[len(scores)] = ["future", pd.Timestamp("2018-08-03"), 0.99]
    attributes.loc[len(attributes)] = ["future", 1, 1, "s9", 0, pd.NaT]
    appended, _ = prepare_review_batches(scores, attributes, assumptions)
    pd.testing.assert_frame_equal(original, appended.loc[appended["order_id"] != "future"].reset_index(drop=True))


def test_unknown_outcomes_use_capacity_and_are_never_counted_as_on_time():
    batch = small_batch(points=(10, 9, 8))
    ids, selection = optimize_reviews(batch, ReviewLimits(11, 3, 3))
    outcomes = pd.DataFrame({"order_id": batch["order_id"], "observed_label_by_cutoff": pd.array([1, None, 0], dtype="Int64")})
    result = evaluate_selected(batch, ids, outcomes)
    assert selection["used_minutes"] == 11
    assert result["selected_orders"] == 2
    assert result["selected_unknown_outcomes"] == 1
    assert result["selected_known_outcomes"] == 1
    assert result["selected_known_late"] == 1
    assert result["observed_late_fraction_among_known_reviews"] == 1


def test_holm_known_family_and_original_order():
    assert holm_adjust([0.01, 0.04, 0.03, 0.001]) == pytest.approx([0.03, 0.06, 0.06, 0.004])


def test_month_adjusted_slope_and_cr1_match_full_dummy_matrix_sandwich():
    rng = np.random.default_rng(73)
    dates = pd.date_range("2018-01-01", periods=90).repeat(4)
    data = pd.DataFrame({"purchased_at": dates, "exposure": rng.integers(0, 2, len(dates)),
                         "is_late": rng.integers(0, 2, len(dates))})
    actual = month_adjusted_contrast(data)
    # An independent full-design implementation, rather than FWL residualization.
    dummies = pd.get_dummies(data["purchased_at"].dt.to_period("M"), dtype=float)
    design = np.column_stack([data["exposure"].to_numpy(), dummies.to_numpy()])
    bread = np.linalg.inv(design.T @ design)
    coefficient = np.linalg.lstsq(design, data["is_late"].to_numpy(), rcond=None)[0]
    residual = data["is_late"].to_numpy() - design @ coefficient
    weeks = data["purchased_at"].dt.to_period("W-SUN")
    meat = np.zeros((design.shape[1], design.shape[1]))
    for week in weeks.unique():
        mask = weeks == week
        score = design[mask].T @ residual[mask]
        meat += np.outer(score, score)
    n, k = design.shape
    groups = weeks.nunique()
    covariance = bread @ meat @ bread * groups / (groups - 1) * (n - 1) / (n - k)
    assert actual["adjusted_difference"] == pytest.approx(coefficient[0], abs=1e-12)
    assert actual["standard_error"] == pytest.approx(np.sqrt(covariance[0, 0]), abs=1e-12)


def test_unknown_outcome_and_no_within_month_contrast_cannot_produce_statistics():
    dates = pd.date_range("2018-01-01", periods=60)
    data = pd.DataFrame({"purchased_at": dates, "exposure": 1, "is_late": 0})
    with pytest.raises(ValueError, match="vary"):
        month_adjusted_contrast(data)
    data["exposure"] = np.arange(60) % 2
    data.loc[0, "is_late"] = np.nan
    with pytest.raises(ValueError, match="known binary"):
        month_adjusted_contrast(data)


def test_incomplete_geocoding_is_not_misclassified_as_short_distance():
    data = pd.DataFrame({"item_count": [2, 2, 1, 1], "items_with_distance": [1, 2, 1, 1],
                         "max_distance_km": [100, 100, 800, 1200]})
    exposure = contrast_exposure(data, "distance")
    assert exposure.isna().tolist() == [True, False, True, False]
    assert exposure.dropna().tolist() == [0, 1]
