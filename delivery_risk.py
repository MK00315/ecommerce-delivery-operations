"""Reproducible estimators, calibrated inference and evaluation for delivery risk."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score, brier_score_loss, confusion_matrix, fbeta_score,
    log_loss, precision_recall_curve, precision_score, recall_score, roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from delivery_features import CATEGORICAL, FEATURES, FORBIDDEN, NUMERIC, STATIC_NUMERIC


def make_estimator(specification, seed=42):
    family = specification["family"]
    parameters = specification["parameters"].copy()
    if family == "dummy":
        return DummyClassifier(strategy="prior", random_state=seed)
    numeric = NUMERIC if specification["history"] else STATIC_NUMERIC
    if family == "logistic":
        continuous = Pipeline([
            ("impute", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
            ("scale", StandardScaler()),
        ])
        categorical = OneHotEncoder(handle_unknown="ignore", min_frequency=50, sparse_output=True)
        preprocess = ColumnTransformer([
            ("numeric", continuous, numeric), ("categorical", categorical, CATEGORICAL),
        ], sparse_threshold=1.0)
        estimator = LogisticRegression(**parameters, solver="lbfgs", random_state=seed)
    elif family == "hist_gradient_boosting":
        preprocess = ColumnTransformer([
            ("numeric", "passthrough", numeric),
            ("categorical", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1,
                                           encoded_missing_value=-1, min_frequency=25, max_categories=100), CATEGORICAL),
        ], sparse_threshold=0)
        estimator = HistGradientBoostingClassifier(
            **parameters, categorical_features=[False] * len(numeric) + [True] * len(CATEGORICAL), random_state=seed)
    else:
        raise ValueError("Unknown model family: " + family)
    return Pipeline([("preprocess", preprocess), ("classifier", estimator)])


def log_odds(probability):
    probability = np.clip(np.asarray(probability, dtype=float), 1e-7, 1 - 1e-7)
    return np.log(probability / (1 - probability)).reshape(-1, 1)


@dataclass
class DeliveryRiskModel:
    estimator: object
    calibrator: object
    threshold: float
    metadata: dict

    def predict_proba(self, features):
        missing = set(FEATURES) - set(features.columns)
        forbidden = set(features.columns) & FORBIDDEN
        if missing or forbidden:
            raise ValueError(f"Invalid feature contract; missing={sorted(missing)}, forbidden={sorted(forbidden)}")
        raw = self.estimator.predict_proba(features[FEATURES])[:, 1]
        probability = self.calibrator.predict_proba(log_odds(raw))[:, 1]
        if not np.isfinite(probability).all():
            raise ValueError("Model returned a non-finite probability.")
        return np.c_[1 - probability, probability]

    def predict(self, features):
        return (self.predict_proba(features)[:, 1] >= self.threshold).astype(int)


def fit_sigmoid(raw_probability, labels):
    if len(np.unique(labels)) != 2:
        raise ValueError("Both outcomes are required for probability calibration.")
    calibrator = LogisticRegression(C=1000.0, solver="lbfgs", max_iter=300)
    calibrator.fit(log_odds(raw_probability), labels)
    if calibrator.coef_[0, 0] <= 0:
        raise ValueError("The calibration slope is non-positive; do not reverse the ranking silently.")
    return calibrator


def f2_threshold(labels, probability):
    precision, recall, thresholds = precision_recall_curve(labels, probability)
    denominator = 4 * precision[:-1] + recall[:-1]
    score = np.divide(5 * precision[:-1] * recall[:-1], denominator,
                      out=np.zeros_like(denominator), where=denominator > 0)
    best = np.flatnonzero(score >= score.max() - 1e-12)[-1]
    return float(thresholds[best])


def ranked_positions(probability, order_ids):
    # The order ID only breaks score ties; it never enters the fitted estimator.
    return np.lexsort((np.asarray(order_ids, dtype=str), -np.asarray(probability, dtype=float)))


def top_fraction(labels, probability, order_ids, fraction=0.1):
    labels = np.asarray(labels, dtype=int)
    number = max(1, int(np.ceil(len(labels) * fraction)))
    selected = ranked_positions(probability, order_ids)[:number]
    captured = int(labels[selected].sum())
    positive = int(labels.sum())
    prevalence = float(labels.mean())
    precision = captured / number
    return {"reviewed_orders": number, "late_orders_captured": captured,
            "precision": float(precision), "recall": captured / positive if positive else None,
            "lift_over_prevalence": precision / prevalence if prevalence else None}


def evaluate(labels, probability, order_ids, threshold=0.5):
    labels = np.asarray(labels, dtype=int)
    probability = np.asarray(probability, dtype=float)
    if not len(labels) or not np.isfinite(probability).all() or ((probability < 0) | (probability > 1)).any():
        raise ValueError("Evaluation requires nonempty labels and finite probabilities in [0,1].")
    predicted = probability >= threshold
    both = len(np.unique(labels)) == 2
    tn, fp, fn, tp = confusion_matrix(labels, predicted, labels=[0, 1]).ravel()
    return {
        "orders": len(labels), "late_orders": int(labels.sum()), "late_rate": float(labels.mean()),
        "average_precision": float(average_precision_score(labels, probability)) if labels.any() else None,
        "roc_auc": float(roc_auc_score(labels, probability)) if both else None,
        "brier_score": float(brier_score_loss(labels, probability)),
        "log_loss": float(log_loss(labels, np.c_[1 - probability, probability], labels=[0, 1])),
        "threshold": float(threshold), "precision": float(precision_score(labels, predicted, zero_division=0)),
        "recall": float(recall_score(labels, predicted, zero_division=0)),
        "f2": float(fbeta_score(labels, predicted, beta=2, zero_division=0)),
        "flagged_orders": int(predicted.sum()), "flagged_share": float(predicted.mean()),
        "confusion_matrix": {"true_negative": int(tn), "false_positive": int(fp), "false_negative": int(fn), "true_positive": int(tp)},
        "top_10_percent": top_fraction(labels, probability, order_ids),
    }


def day_block_intervals(labels, probability, order_ids, days, repetitions=400, seed=42):
    labels, probability = np.asarray(labels, dtype=int), np.asarray(probability, dtype=float)
    ids, days = np.asarray(order_ids, dtype=str), np.asarray(days, dtype="datetime64[D]")
    unique = np.unique(days)
    groups = [np.flatnonzero(days == day) for day in unique]
    generator = np.random.default_rng(seed)
    values = {"average_precision": [], "roc_auc": [], "brier_score": [], "top_10_percent_recall": []}
    for _ in range(repetitions):
        indices = np.concatenate([groups[index] for index in generator.integers(0, len(groups), len(groups))])
        y, p = labels[indices], probability[indices]
        if len(np.unique(y)) != 2:
            continue
        values["average_precision"].append(float(average_precision_score(y, p)))
        values["roc_auc"].append(float(roc_auc_score(y, p)))
        values["brier_score"].append(float(brier_score_loss(y, p)))
        values["top_10_percent_recall"].append(top_fraction(y, p, ids[indices])["recall"])
    return {"method": "Approval-calendar-day block bootstrap; within-day clustering retained, between-day dependence not modeled",
            "calendar_day_blocks": len(groups), "requested_repetitions": repetitions,
            "valid_repetitions": len(values["average_precision"]), "confidence": 0.95,
            "intervals": {name: {"low": float(np.quantile(data, 0.025)), "high": float(np.quantile(data, 0.975))}
                          for name, data in values.items()}}
