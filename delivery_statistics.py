"""Exploratory order-grain associations with month effects and clustered uncertainty."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import t as student_t


def holm_adjust(p_values):
    """Holm step-down family-wise error adjustment, preserving the input order."""
    values = np.asarray(p_values, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError("p-values must be a finite vector in [0, 1].")
    order = np.argsort(values, kind="stable")
    adjusted = np.empty(len(values))
    adjusted[order] = np.minimum(1, np.maximum.accumulate(values[order] * np.arange(len(values), 0, -1)))
    return adjusted


def month_adjusted_contrast(frame, cluster="week"):
    """FWL slope for late ~ exposure + month FE; one-way CR1 sandwich variance.

    This estimates a conditional *association*. The binary-outcome regression is
    an effect-size calculation, never an individual probability prediction.
    """
    needed = ["is_late", "exposure", "purchased_at"]
    data = frame[needed].copy()
    if data.isna().any().any() or not data["is_late"].isin([0, 1]).all() or not data["exposure"].isin([0, 1]).all():
        raise ValueError("Contrasts need known binary outcomes/exposures and purchase timestamps.")
    if cluster not in {"day", "week"}:
        raise ValueError("Use day or week clusters.")
    data["month"] = data["purchased_at"].dt.to_period("M").astype(str)
    x = data["exposure"].to_numpy(dtype=float)
    y = data["is_late"].to_numpy(dtype=float)
    xr = x - data.groupby("month")["exposure"].transform("mean").to_numpy()
    yr = y - data.groupby("month")["is_late"].transform("mean").to_numpy()
    denominator = float(xr @ xr)
    n, k = len(data), data["month"].nunique() + 1
    if denominator < 1e-10 or n <= k:
        raise ValueError("Exposure must vary within at least one month and leave residual degrees of freedom.")
    beta = float(xr @ yr / denominator)
    residual = yr - beta * xr
    dates = data["purchased_at"].dt.normalize()
    if cluster == "week":
        dates = dates.dt.to_period("W-SUN").dt.start_time
    codes, names = pd.factorize(dates, sort=True)
    groups = len(names)
    if groups < 3:
        raise ValueError("At least three time clusters are required.")
    scores = np.bincount(codes, weights=xr * residual, minlength=groups)
    correction = groups / (groups - 1) * (n - 1) / (n - k)
    se = float(np.sqrt(correction * (scores @ scores) / denominator**2))
    critical = float(student_t.ppf(0.975, groups - 1))
    p = float(2 * student_t.sf(abs(beta / se), groups - 1)) if se > 0 else (0.0 if beta else 1.0)
    return {"orders": n, "months": int(k - 1), "clusters": groups, "cluster_unit": cluster,
            "adjusted_difference": beta, "standard_error": se,
            "ci_low": beta - critical * se, "ci_high": beta + critical * se,
            "p_value": p, "residual_df": int(n - k), "cluster_df": groups - 1}


def contrast_exposure(data, contrast_id):
    """1 is the named exposure; missing/out-of-contrast rows stay unknown."""
    result = pd.Series(np.nan, index=data.index)
    if contrast_id == "distance":
        valid = (data["item_count"] > 0) & (data["items_with_distance"] == data["item_count"])
        result.loc[valid & (data["max_distance_km"] <= 500)] = 0
        result.loc[valid & (data["max_distance_km"] > 1000)] = 1
    elif contrast_id == "basket":
        result.loc[data["item_count"] == 1] = 0
        result.loc[data["item_count"] >= 2] = 1
    elif contrast_id == "promise":
        result.loc[data["promised_calendar_days"] > 14] = 0
        result.loc[data["promised_calendar_days"].between(0, 14)] = 1
    elif contrast_id == "interstate":
        valid = (data["item_count"] > 0) & (data["items_with_state"] == data["item_count"])
        result.loc[valid & ~data["any_interstate"].fillna(False)] = 0
        result.loc[valid & data["any_interstate"].fillna(False)] = 1
    else:
        raise ValueError("Unknown contrast.")
    return result


def analyse_contrasts(eligible, hypotheses):
    results = []
    for spec in hypotheses:
        data = eligible.assign(exposure=contrast_exposure(eligible, spec["id"]))
        known = data.dropna(subset=["exposure"])
        result = {"id": spec["id"], "label": spec["label"],
                  "eligible_orders": len(eligible), "excluded_from_contrast": len(data) - len(known)}
        for exposure, name in [(0, "reference"), (1, "exposed")]:
            group = known.loc[known["exposure"] == exposure, "is_late"]
            result.update({f"{name}_orders": len(group), f"{name}_late": int(group.sum()),
                           f"{name}_rate": float(group.mean())})
        result["unadjusted_difference"] = result["exposed_rate"] - result["reference_rate"]
        result.update(month_adjusted_contrast(known, "week"))
        sensitivity = month_adjusted_contrast(known, "day")
        result.update({"day_cluster_ci_low": sensitivity["ci_low"],
                       "day_cluster_ci_high": sensitivity["ci_high"], "day_clusters": sensitivity["clusters"]})
        results.append(result)
    for result, adjusted in zip(results, holm_adjust([r["p_value"] for r in results])):
        result["holm_p_value"] = float(adjusted)
        result["reject_at_005_holm"] = bool(adjusted < 0.05)
    return pd.DataFrame(results)


def descriptive_groups(eligible):
    """Each grouping partitions all eligible orders, including an unknown bucket."""
    data = eligible.copy()
    distance = pd.cut(data["max_distance_km"], [-np.inf, 500, 1000, 2000, np.inf],
                      labels=["<=500 km", "500-1,000 km", "1,000-2,000 km", ">2,000 km"]).astype(object)
    distance.loc[(data["item_count"] == 0) | (data["items_with_distance"] != data["item_count"])] = "Unknown/incomplete"
    data["distance_group"] = distance.fillna("Unknown/incomplete")
    data["basket_group"] = pd.cut(data["item_count"], [-1, 0, 1, 3, np.inf],
                                 labels=["Missing basket", "1 item", "2-3 items", "4+ items"]).astype(str)
    data["promise_group"] = pd.cut(data["promised_calendar_days"], [-1, 7, 14, 21, 30, np.inf],
                                  labels=["0-7 days", "8-14 days", "15-21 days", "22-30 days", "31+ days"]).astype(str)
    data["customer_state"] = data["customer_state"].fillna("Unknown")
    data["purchase_month_label"] = data["purchased_at"].dt.to_period("M").astype(str)
    tables = []
    for name in ["distance_group", "basket_group", "promise_group", "customer_state", "purchase_month_label"]:
        table = data.groupby(name, observed=True, dropna=False).agg(
            orders=("order_id", "size"), late_orders=("is_late", "sum"),
            median_delivery_days=("delivery_days", "median")).reset_index(names="group")
        table["late_rate"] = table["late_orders"] / table["orders"]
        table["dimension"] = name
        table["small_group_under_100"] = table["orders"] < 100
        if int(table["orders"].sum()) != len(eligible):
            raise AssertionError("A descriptive partition lost or duplicated orders.")
        tables.append(table)
    return pd.concat(tables, ignore_index=True)
