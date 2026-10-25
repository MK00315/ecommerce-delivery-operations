"""Temporal leakage, label maturity and inference contract boundaries."""
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_features import CATEGORICAL, FEATURES, history_features, mature_window, prior_stats
from delivery_risk import DeliveryRiskModel, ranked_positions
from train_delivery_rolling import assert_protocol


def test_history_uses_closed_left_open_right_window_and_excludes_timestamp_ties():
    moment = pd.Timestamp("2018-08-01 10:00:00")
    events = [moment - pd.Timedelta(days=8), moment - pd.Timedelta(days=7),
              moment - pd.Timedelta(days=1), moment, moment + pd.Timedelta(days=1)]
    count, late, latest = prior_stats(events, [1, 1, 0, 1, 1], [moment], days=7)
    assert count.tolist() == [2]
    assert late.tolist() == [1]
    assert latest[0] == moment - pd.Timedelta(days=1)


def history_fixture():
    queries = pd.DataFrame({"order_id": ["query"], "approved_at": pd.to_datetime(["2018-08-01 10:00:00"])})
    links = pd.DataFrame({"order_id": ["query", "query", "old", "future", "same_time"],
                          "seller_id": ["seller", "seller", "seller", "seller", "seller"]})
    outcomes = pd.DataFrame({"order_id": ["old", "future", "same_time"],
                             "delivered_at": pd.to_datetime(["2018-07-31 10:00:00", "2018-08-02 10:00:00", "2018-08-01 10:00:00"]),
                             "is_late": [0, 1, 1]})
    approvals = pd.DataFrame({"order_id": ["old", "future", "same_time", "query"],
                              "approved_at": pd.to_datetime(["2018-07-30 10:00:00", "2018-08-02 10:00:00", "2018-08-01 10:00:00", "2018-08-01 10:00:00"])})
    return queries, links, outcomes, approvals


def test_future_outcome_changes_cannot_change_an_earlier_prediction_feature():
    queries, links, outcomes, approvals = history_fixture()
    original, audit = history_features(queries, links, outcomes, approvals)
    outcomes.loc[outcomes["order_id"] == "future", "is_late"] = 0
    outcomes.loc[outcomes["order_id"] == "future", "delivered_at"] = pd.Timestamp("2018-08-20")
    changed, changed_audit = history_features(queries, links, outcomes, approvals)
    pd.testing.assert_frame_equal(original, changed)
    pd.testing.assert_frame_equal(audit, changed_audit)


def test_repeated_item_links_do_not_inflate_seller_history_or_count_current_batch():
    result, _ = history_features(*history_fixture())
    assert result.loc[0, "seller_completed_90d_mean"] == 1
    assert result.loc[0, "seller_approvals_7d_mean"] == 1
    assert result.loc[0, "global_completed_90d"] == 1
    assert result.loc[0, "global_late_rate_90d"] == pytest.approx(1 / 3)


def test_unseen_seller_uses_past_global_prior_and_explicit_cold_start_flag():
    queries, links, outcomes, approvals = history_fixture()
    links.loc[links["order_id"] == "query", "seller_id"] = "new_seller"
    result, _ = history_features(queries, links, outcomes, approvals)
    assert result.loc[0, "seller_cold_start_fraction"] == 1
    assert result.loc[0, "seller_late_rate_90d_mean"] == pytest.approx(1 / 3)
    assert result.loc[0, "seller_completed_90d_mean"] == 0


def test_outcome_at_or_after_fit_cutoff_and_unknown_labels_are_not_training_rows():
    metadata = pd.DataFrame({
        "approved_at": pd.to_datetime(["2018-01-05"] * 4),
        "delivered_at": pd.to_datetime(["2018-01-31 23:59:59", "2018-02-01", "2018-02-02", None], format="ISO8601"),
        "outcome_valid": [True, True, True, False],
        "target": pd.array([0, 1, 1, None], dtype="Int64"),
    }, index=["known", "tie", "future", "unknown"])
    ids, coverage = mature_window(metadata, {"approval_start": "2018-01-01", "approval_end": "2018-02-01", "outcomes_before": "2018-02-01"})
    assert ids.tolist() == ["known"]
    assert coverage["not_evaluable_by_cutoff"] == 3


@pytest.mark.parametrize("column", ["is_late", "delivered_at", "latest_review_score", "order_status"])
def test_inference_rejects_outcome_fields_even_when_all_valid_features_are_present(column):
    frame = pd.DataFrame({name: ["__missing__" if name in CATEGORICAL else 0.0] for name in FEATURES})
    frame[column] = 1
    bundle = DeliveryRiskModel(None, None, 0.5, {})
    with pytest.raises(ValueError, match="forbidden"):
        bundle.predict_proba(frame)


def test_equal_scores_are_ordered_by_id_without_looking_at_outcomes():
    assert ranked_positions([0.2, 0.2], ["b", "a"]).tolist() == [1, 0]


def test_empty_history_preserves_cold_start_instead_of_reading_future_outcomes():
    queries, links, outcomes, approvals = history_fixture()
    outcomes = outcomes.iloc[:0]
    result, _ = history_features(queries, links, outcomes, approvals)
    assert result.loc[0, "global_late_rate_90d"] == 0.5
    assert result.loc[0, "seller_late_rate_90d_mean"] == 0.5
    assert np.isfinite(result.select_dtypes(include=["number"]).to_numpy()).all()


@pytest.mark.parametrize("field,value", [
    ("fit_approval_end", "2018-03-01"),
    ("fit_outcomes_before", "2018-03-02"),
    ("validation_end", "2018-09-01"),
])
def test_rolling_protocol_rejects_future_information_in_candidate_selection(field, value):
    path = Path(__file__).resolve().parents[1] / "modeling_protocol_rolling.json"
    protocol = json.loads(path.read_text())
    protocol["folds"][0][field] = value
    with pytest.raises(AssertionError):
        assert_protocol(protocol)


def test_final_refit_cannot_use_outcomes_after_simulated_deployment():
    path = Path(__file__).resolve().parents[1] / "modeling_protocol_rolling.json"
    protocol = json.loads(path.read_text())
    protocol["final_refit"]["outcomes_before"] = "2018-08-02"
    with pytest.raises(AssertionError):
        assert_protocol(protocol)
