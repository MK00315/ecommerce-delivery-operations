"""Approval-time basket features and strictly earlier observed seller history."""
from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

FEATURE_VERSION = "1.0.0"
STATIC_NUMERIC = [
    "promised_window_days", "approval_wait_hours", "item_count", "seller_count", "product_count",
    "category_count", "seller_state_count", "item_value", "freight_value", "freight_share",
    "value_per_item", "freight_per_item", "known_weight_g", "max_item_weight_g", "weight_coverage",
    "known_volume_cm3", "max_item_volume_cm3", "volume_coverage", "max_distance_km",
    "mean_distance_km", "distance_coverage", "known_interstate_share",
    "hour_sin", "hour_cos", "weekday_sin", "weekday_cos", "month_sin", "month_cos",
]
HISTORY_NUMERIC = [
    "global_completed_30d", "global_completed_90d", "global_late_rate_30d", "global_late_rate_90d",
    "global_approvals_7d", "seller_completed_90d_mean", "seller_completed_90d_min",
    "seller_late_rate_90d_mean", "seller_late_rate_90d_max", "seller_approvals_7d_mean",
    "seller_approvals_7d_max", "seller_approvals_30d_mean", "seller_approvals_30d_max",
    "seller_cold_start_fraction",
]
CATEGORICAL = ["customer_state", "main_seller_state", "main_category"]
NUMERIC = STATIC_NUMERIC + HISTORY_NUMERIC
FEATURES = NUMERIC + CATEGORICAL
FORBIDDEN = {
    "is_late", "late_calendar_days", "delivery_days", "delivered_at", "carrier_at",
    "seller_handling_days", "carrier_transit_days", "latest_review_score", "review_score",
    "latest_review_answered_at", "review_count", "order_status", "sla_eligible",
    "recorded_payment_value", "payment_count", "customer_unique_id", "order_id", "seller_id",
}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prior_stats(event_times, event_values, query_times, days=None):
    """Count/sum events in [t-window, t), with strict exclusion of all ties at t."""
    times = np.asarray(event_times, dtype="datetime64[ns]")
    queries = np.asarray(query_times, dtype="datetime64[ns]")
    values = np.asarray(event_values, dtype=float)
    valid = ~np.isnat(times)
    times, values = times[valid], values[valid]
    order = np.argsort(times, kind="stable")
    times, values = times[order], values[order]
    end = np.searchsorted(times, queries, side="left")
    begin = np.zeros(len(queries), dtype=int) if days is None else np.searchsorted(
        times, queries - np.timedelta64(days, "D"), side="left")
    cumulative = np.r_[0.0, np.cumsum(values)]
    last = np.full(len(queries), np.datetime64("NaT", "ns"))
    known = end > begin
    last[known] = times[end[known] - 1]
    return end - begin, cumulative[end] - cumulative[begin], last


def history_features(queries, links, outcomes, approvals, pseudo_orders=20):
    """Build history for each order using only events observed before its approval.

    queries/approvals: order_id, approved_at; links: order_id, seller_id;
    outcomes: order_id, delivered_at, is_late. All IDs remain outside model inputs.
    """
    queries = queries[["order_id", "approved_at"]].copy().reset_index(drop=True)
    if not queries["order_id"].is_unique:
        raise ValueError("Queries must contain one row per order.")
    links = links[["order_id", "seller_id"]].drop_duplicates()
    outcomes = outcomes.dropna(subset=["delivered_at", "is_late"])
    if not outcomes["order_id"].is_unique:
        raise ValueError("Observed outcomes must contain one row per order.")
    output = pd.DataFrame(index=queries.index)
    output["order_id"] = queries["order_id"]
    audits = pd.DataFrame({"order_id": queries["order_id"]})
    audits["latest_history_outcome_at"] = pd.NaT
    for days in [30, 90]:
        count, late, last = prior_stats(outcomes["delivered_at"], outcomes["is_late"], queries["approved_at"], days)
        output[f"global_completed_{days}d"] = count
        output[f"global_late_rate_{days}d"] = (late + 1.0) / (count + 2.0)
        if days == 90:
            audits["latest_history_outcome_at"] = last
    output["global_approvals_7d"] = prior_stats(
        approvals["approved_at"], np.ones(len(approvals)), queries["approved_at"], 7)[0]
    query_links = queries.merge(links, on="order_id", how="left", validate="one_to_many")
    if query_links["seller_id"].isna().any():
        raise ValueError("Every scored basket must have a known source seller link.")
    query_links = query_links.merge(output[["order_id", "global_late_rate_90d"]], on="order_id", validate="many_to_one")
    outcome_links = links.merge(outcomes, on="order_id", validate="many_to_one")
    approval_links = links.merge(approvals, on="order_id", validate="many_to_one")
    outcome_groups = {key: group for key, group in outcome_links.groupby("seller_id", sort=False)}
    approval_groups = {key: group for key, group in approval_links.groupby("seller_id", sort=False)}
    empty_outcome = outcomes.iloc[:0]
    empty_approval = approvals.iloc[:0]
    parts = []
    for seller, group in query_links.groupby("seller_id", sort=False):
        group = group.copy()
        observed = outcome_groups.get(seller, empty_outcome)
        count, late, last = prior_stats(observed["delivered_at"], observed["is_late"], group["approved_at"], 90)
        group["completed"] = count
        group["late_rate"] = (late + pseudo_orders * group["global_late_rate_90d"].to_numpy()) / (count + pseudo_orders)
        group["cold"] = (count == 0).astype(float)
        group["latest_seller_outcome_at"] = last
        previous = approval_groups.get(seller, empty_approval)
        for days in [7, 30]:
            counts, _, latest = prior_stats(previous["approved_at"], np.ones(len(previous)), group["approved_at"], days)
            group[f"approvals_{days}"] = counts
            if days == 30:
                group["latest_seller_approval_at"] = latest
        parts.append(group)
    details = pd.concat(parts, ignore_index=True)
    aggregate = details.groupby("order_id", sort=False).agg(
        seller_completed_90d_mean=("completed", "mean"), seller_completed_90d_min=("completed", "min"),
        seller_late_rate_90d_mean=("late_rate", "mean"), seller_late_rate_90d_max=("late_rate", "max"),
        seller_approvals_7d_mean=("approvals_7", "mean"), seller_approvals_7d_max=("approvals_7", "max"),
        seller_approvals_30d_mean=("approvals_30", "mean"), seller_approvals_30d_max=("approvals_30", "max"),
        seller_cold_start_fraction=("cold", "mean"), latest_seller_outcome_at=("latest_seller_outcome_at", "max"),
        latest_history_approval_at=("latest_seller_approval_at", "max"),
    ).reset_index()
    audits = audits.merge(aggregate[["order_id", "latest_seller_outcome_at", "latest_history_approval_at"]], on="order_id", validate="one_to_one")
    output = output.merge(aggregate.drop(columns=["latest_seller_outcome_at", "latest_history_approval_at"]), on="order_id", validate="one_to_one")
    for column in ["latest_history_outcome_at", "latest_seller_outcome_at", "latest_history_approval_at"]:
        observed = pd.to_datetime(audits[column])
        if not (observed.isna() | (observed < queries["approved_at"])).all():
            raise ValueError("A history event was not strictly earlier than its prediction time.")
    return output, audits


BASE_SQL = """
WITH category_counts AS (
    SELECT order_id,coalesce(category,'__missing__') category,count(*) n,
           row_number() OVER(PARTITION BY order_id ORDER BY count(*) DESC,coalesce(category,'__missing__')) rn
    FROM gold.order_items GROUP BY order_id,category
), state_counts AS (
    SELECT order_id,coalesce(seller_state,'__missing__') seller_state,count(*) n,
           row_number() OVER(PARTITION BY order_id ORDER BY count(*) DESC,coalesce(seller_state,'__missing__')) rn
    FROM gold.order_items GROUP BY order_id,seller_state
), extra AS (
    SELECT order_id,count(DISTINCT category) category_count,count(DISTINCT seller_state) seller_state_count,
           max(weight_g) max_item_weight_g,
           sum(CASE WHEN volume_cm3>0 THEN volume_cm3 END) known_volume_cm3,
           max(CASE WHEN volume_cm3>0 THEN volume_cm3 END) max_item_volume_cm3,
           count(*) FILTER(WHERE volume_cm3>0) items_with_volume,
           avg(CASE WHEN seller_state IS NOT NULL AND customer_state IS NOT NULL
                    THEN cast(seller_state<>customer_state AS DOUBLE) END) known_interstate_share
    FROM gold.order_items GROUP BY order_id
)
SELECT o.order_id,o.purchased_at,o.approved_at,o.promised_at,o.delivered_at,o.order_status,o.sla_eligible,o.is_late,
       o.customer_state,o.item_count,o.seller_count,o.product_count,o.item_value,o.freight_value,o.known_weight_g,
       o.items_with_weight,o.items_with_distance,o.max_distance_km,o.mean_distance_km,
       x.* EXCLUDE(order_id),c.category main_category,s.seller_state main_seller_state
FROM gold.orders o
LEFT JOIN extra x USING(order_id)
LEFT JOIN category_counts c ON o.order_id=c.order_id AND c.rn=1
LEFT JOIN state_counts s ON o.order_id=s.order_id AND s.rn=1
ORDER BY o.approved_at,o.order_id
"""


def build_features(root: Path, pseudo_orders=20):
    with duckdb.connect(str(root / "data/interim/delivery_operations.duckdb"), read_only=True) as connection:
        base = connection.execute(BASE_SQL).df()
        links = connection.execute("SELECT order_id,seller_id FROM gold.order_sellers").df()
    if not base["order_id"].is_unique:
        raise ValueError("Basket joins changed the order grain.")
    decision_valid = (
        base["approved_at"].notna() & base["purchased_at"].notna() & base["promised_at"].notna()
        & (base["approved_at"] >= base["purchased_at"])
        & (base["promised_at"].dt.normalize() >= base["approved_at"].dt.normalize())
        & (base["item_count"] > 0)
    )
    # This filter uses no future delivery/status/review information.
    decisions = base.loc[decision_valid].copy().reset_index(drop=True)
    frame = decisions[["order_id", "customer_state", "main_seller_state", "main_category"]].copy()
    direct = ["item_count", "seller_count", "product_count", "category_count", "seller_state_count", "item_value",
              "freight_value", "known_weight_g", "max_item_weight_g", "known_volume_cm3", "max_item_volume_cm3",
              "max_distance_km", "mean_distance_km", "known_interstate_share"]
    for column in direct:
        frame[column] = decisions[column].astype(float)
    frame["promised_window_days"] = ((decisions["promised_at"].dt.normalize() + pd.Timedelta(days=1) - decisions["approved_at"]).dt.total_seconds() / 86400)
    frame["approval_wait_hours"] = (decisions["approved_at"] - decisions["purchased_at"]).dt.total_seconds() / 3600
    frame["freight_share"] = decisions["freight_value"] / (decisions["freight_value"] + decisions["item_value"]).replace(0, np.nan)
    frame["value_per_item"] = decisions["item_value"] / decisions["item_count"]
    frame["freight_per_item"] = decisions["freight_value"] / decisions["item_count"]
    for output, numerator in [("weight_coverage", "items_with_weight"), ("volume_coverage", "items_with_volume"), ("distance_coverage", "items_with_distance")]:
        frame[output] = decisions[numerator].fillna(0) / decisions["item_count"]
    for prefix, values, period in [
        ("hour", decisions["approved_at"].dt.hour, 24),
        ("weekday", decisions["approved_at"].dt.dayofweek, 7),
        ("month", decisions["approved_at"].dt.month - 1, 12),
    ]:
        frame[prefix + "_sin"] = np.sin(2 * np.pi * values / period)
        frame[prefix + "_cos"] = np.cos(2 * np.pi * values / period)
    valid_outcome = base["sla_eligible"].fillna(False) & (base["approved_at"].isna() | (base["delivered_at"] >= base["approved_at"]))
    outcomes = base.loc[valid_outcome, ["order_id", "delivered_at", "is_late"]]
    valid_approval = base["approved_at"].notna() & (base["approved_at"] >= base["purchased_at"])
    approvals = base.loc[valid_approval, ["order_id", "approved_at"]]
    histories, audits = history_features(decisions, links, outcomes, approvals, pseudo_orders)
    frame = frame.merge(histories, on="order_id", validate="one_to_one")
    for column in NUMERIC:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
        frame[column] = frame[column].replace([np.inf, -np.inf], np.nan)
    for column in CATEGORICAL:
        frame[column] = frame[column].fillna("__missing__").astype(object)
    if set(FEATURES) & FORBIDDEN:
        raise ValueError("A forbidden outcome or identifier entered the feature contract.")
    metadata = decisions[["order_id", "purchased_at", "approved_at", "promised_at", "delivered_at", "order_status", "sla_eligible", "is_late"]].copy()
    metadata["outcome_valid"] = decisions["sla_eligible"].fillna(False) & (decisions["delivered_at"] >= decisions["approved_at"])
    metadata["target"] = decisions["is_late"].where(metadata["outcome_valid"]).astype("Int64")
    metadata = metadata.merge(audits, on="order_id", validate="one_to_one")
    frame = frame.set_index("order_id")[FEATURES]
    metadata = metadata.set_index("order_id").loc[frame.index]
    audit = {
        "feature_version": FEATURE_VERSION, "original_orders": len(base), "valid_approval_decisions": len(frame),
        "valid_delivered_prediction_outcomes": int(metadata["outcome_valid"].sum()),
        "missing_approval_timestamp": int(base["approved_at"].isna().sum()),
        "approval_before_purchase": int((base["approved_at"] < base["purchased_at"]).sum()),
        "approval_after_actual_delivery": int((base["approved_at"] > base["delivered_at"]).sum()),
        "promise_date_before_approval_date": int((base["promised_at"].dt.normalize() < base["approved_at"].dt.normalize()).sum()),
        "missing_basket": int((base["item_count"] == 0).sum()),
        "exclusion_counts_can_overlap": True, "history_boundary": "Strictly before approval, including exclusion of timestamp ties",
        "seller_history_grain": "One completed/approved order per distinct associated seller, not one event per item",
        "feature_count": len(FEATURES), "features": FEATURES,
        "forbidden_fields_in_features": sorted(set(FEATURES) & FORBIDDEN),
        "source_database_sha256": digest(root / "data/interim/delivery_operations.duckdb"),
    }
    return frame, metadata, audit


def mature_window(metadata, specification):
    period = (metadata["approved_at"] >= pd.Timestamp(specification["approval_start"])) & (metadata["approved_at"] < pd.Timestamp(specification["approval_end"]))
    observed = metadata["outcome_valid"] & (metadata["delivered_at"] < pd.Timestamp(specification["outcomes_before"]))
    selected = metadata.index[period & observed]
    coverage = {
        **specification, "valid_decisions": int(period.sum()), "observed_evaluable_orders": len(selected),
        "not_evaluable_by_cutoff": int((period & ~observed).sum()),
        "observed_outcome_coverage": float((period & observed).sum() / period.sum()) if period.any() else None,
        "late_orders": int(metadata.loc[selected, "target"].sum()),
    }
    return selected, coverage
