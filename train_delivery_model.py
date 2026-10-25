"""Prepare, select, refit, calibrate and evaluate a chronological delivery-risk model."""
from __future__ import annotations

import os

for _variable in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
    os.environ.setdefault(_variable, "4")

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import time
import warnings

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import average_precision_score, precision_recall_curve
from threadpoolctl import threadpool_limits

from delivery_features import CATEGORICAL, FEATURES, FEATURE_VERSION, build_features, digest, mature_window
from delivery_pipeline import source_manifest, write_json
from delivery_risk import (
    DeliveryRiskModel, day_block_intervals, evaluate, f2_threshold, fit_sigmoid,
    log_odds, make_estimator, ranked_positions,
)

ROOT = Path(__file__).resolve().parent
SOURCE_FILES = ["delivery_features.py", "delivery_risk.py", "train_delivery_model.py", "modeling_protocol.json"]


def log(message):
    print(message, flush=True)


def protocol_checks(protocol):
    train, validation = protocol["selection_train"], protocol["selection_validation"]
    refit, calibration, holdout = [protocol[key] for key in ["final_refit", "calibration_and_threshold_development", "holdout_test"]]
    assert pd.Timestamp(train["approval_end"]) <= pd.Timestamp(train["outcomes_before"]) <= pd.Timestamp(validation["approval_start"])
    assert pd.Timestamp(validation["outcomes_before"]) <= pd.Timestamp(refit["outcomes_before"])
    assert pd.Timestamp(refit["approval_end"]) < pd.Timestamp(calibration["approval_start"])
    assert pd.Timestamp(refit["outcomes_before"]) <= pd.Timestamp(calibration["approval_start"])
    assert pd.Timestamp(calibration["approval_end"]) <= pd.Timestamp(calibration["outcomes_before"]) <= pd.Timestamp(holdout["approval_start"])
    assert len({item["name"] for item in protocol["candidates"]}) == len(protocol["candidates"])


def prepare(root):
    protocol = json.loads((root / "modeling_protocol.json").read_text())
    protocol_checks(protocol)
    source_manifest(root)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = root / "reports/modeling" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "protocol.json").write_bytes((root / "modeling_protocol.json").read_bytes())
    log("Building approval-time features with strictly earlier observed history...")
    features, metadata, audit = build_features(root, protocol["seller_prior_pseudo_orders"])
    data_dir = root / "data/processed/ml" / run_id
    data_dir.mkdir(parents=True, exist_ok=False)
    features.to_parquet(data_dir / "features.parquet", compression="zstd")
    metadata.to_parquet(data_dir / "metadata.parquet", compression="zstd")
    splits = {}
    for name in ["selection_train", "selection_validation", "final_refit", "calibration_and_threshold_development", "holdout_test"]:
        ids, coverage = mature_window(metadata, protocol[name])
        if len(ids) < 100 or metadata.loc[ids, "target"].nunique() != 2:
            raise ValueError("An evaluation cohort is too small or lacks both outcomes: " + name)
        splits[name] = coverage
    audit["data_directory"] = data_dir.relative_to(root).as_posix()
    audit["artifacts"] = {name: digest(data_dir / name) for name in ["features.parquet", "metadata.parquet"]}
    audit["source_code_sha256"] = {name: digest(root / name) for name in SOURCE_FILES}
    audit["protocol_sha256"] = digest(run_dir / "protocol.json")
    write_json(run_dir / "feature_audit.json", audit)
    write_json(run_dir / "cohorts.json", splits)
    write_json(root / "reports/modeling/latest_prepared.json", {"run_id": run_id, "run_directory": run_dir.relative_to(root).as_posix()})
    log(json.dumps({"run_id": run_id, "features": len(FEATURES), "valid_decisions": len(features), "cohorts": splits}, indent=2))
    return run_id


def calibration_bins(labels, probability):
    table = pd.DataFrame({"probability": probability, "target": np.asarray(labels, dtype=int)})
    table["bin"] = pd.qcut(table["probability"], q=10, duplicates="drop")
    return table.groupby("bin", observed=True).agg(
        orders=("target", "size"), late_orders=("target", "sum"),
        mean_predicted_probability=("probability", "mean"), observed_late_rate=("target", "mean"),
    ).reset_index(drop=True)


def make_figures(run_dir, labels, probability, raw_probability, baseline_probability, ids, bins,
                 evaluation_label="August 2018 holdout"):
    directory = run_dir / "figures"
    directory.mkdir(exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.labelcolor": "#334155", "text.color": "#0f172a",
                         "axes.titleweight": "bold", "savefig.facecolor": "white", "figure.dpi": 120})
    blue, orange, gray = "#0284c7", "#d97706", "#64748b"
    figure, axis = plt.subplots(figsize=(9, 5.8), layout="constrained")
    curves = [(probability, "Selected model", blue)]
    if not np.allclose(probability, baseline_probability, rtol=0, atol=1e-12):
        curves.append((baseline_probability, "Static logistic baseline", orange))
    for values, name, color in curves:
        precision, recall, _ = precision_recall_curve(labels, values)
        axis.plot(recall, precision, color=color, lw=2.3,
                  label=f"{name} (AP {average_precision_score(labels, values):.3f})")
    axis.axhline(np.mean(labels), color=gray, ls="--", label=f"Observed late rate {np.mean(labels):.1%}")
    axis.set(xlim=(0, 1), ylim=(0, 1), xlabel="Recall: share of late deliveries found",
             ylabel="Precision: late share among flagged orders", title=evaluation_label + ": precision and recall")
    axis.grid(alpha=0.15)
    axis.legend(frameon=False)
    figure.savefig(directory / "precision_recall.png", dpi=180, bbox_inches="tight", pad_inches=0.15)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(9, 5.8), layout="constrained")
    axis.plot([0, 1], [0, 1], ls="--", color=gray, label="Ideal calibration")
    axis.plot(bins["mean_predicted_probability"], bins["observed_late_rate"], "o-", color=blue, lw=2,
              label="Sigmoid-adjusted model, equal-count bins")
    raw_bins = calibration_bins(labels, raw_probability)
    axis.plot(raw_bins["mean_predicted_probability"], raw_bins["observed_late_rate"], "s--", color=orange,
              label="Raw model, equal-count bins")
    maximum = min(1, max(0.3, float(bins[["mean_predicted_probability", "observed_late_rate"]].max().max()) * 1.15,
                         float(raw_bins[["mean_predicted_probability", "observed_late_rate"]].max().max()) * 1.15))
    axis.set(xlim=(0, maximum), ylim=(0, maximum), xlabel="Mean predicted probability",
             ylabel="Observed late rate", title=evaluation_label + ": probability reliability")
    axis.grid(alpha=0.15)
    axis.legend(frameon=False)
    figure.savefig(directory / "calibration.png", dpi=180, bbox_inches="tight", pad_inches=0.15)
    plt.close(figure)

    order = ranked_positions(probability, ids)
    captured = np.r_[0, np.cumsum(np.asarray(labels)[order]) / np.sum(labels)]
    reviewed = np.arange(len(labels) + 1) / len(labels)
    figure, axis = plt.subplots(figsize=(9, 5.8), layout="constrained")
    axis.plot(reviewed, captured, color=blue, lw=2.5, label="Selected model")
    axis.plot([0, 1], [0, 1], color=gray, ls="--", label="Random review reference")
    axis.axvline(0.1, color=orange, ls=":", label="10% ranking diagnostic")
    axis.set(xlim=(0, 1), ylim=(0, 1), xlabel="Share of evaluable orders reviewed",
             ylabel="Share of late deliveries captured", title=evaluation_label + ": cumulative late-delivery capture")
    axis.grid(alpha=0.15)
    axis.legend(frameon=False)
    figure.savefig(directory / "review_capture.png", dpi=180, bbox_inches="tight", pad_inches=0.15)
    plt.close(figure)


def permutation_diagnostic(bundle, features, labels, seed=42):
    generator = np.random.default_rng(seed)
    original = average_precision_score(labels, bundle.predict_proba(features)[:, 1])
    results = []
    for column in FEATURES:
        differences = []
        for _ in range(3):
            changed = features.copy()
            changed[column] = generator.permutation(changed[column].to_numpy())
            score = average_precision_score(labels, bundle.predict_proba(changed)[:, 1])
            differences.append(original - score)
        results.append({"feature": column, "mean_ap_decrease": float(np.mean(differences)),
                        "std_ap_decrease": float(np.std(differences)), "repetitions": 3})
    return pd.DataFrame(results).sort_values("mean_ap_decrease", ascending=False)


def train(root, run_id):
    started = time.perf_counter()
    run_dir = root / "reports/modeling" / run_id
    protocol = json.loads((run_dir / "protocol.json").read_text())
    protocol_checks(protocol)
    audit = json.loads((run_dir / "feature_audit.json").read_text())
    data_dir = root / audit["data_directory"]
    for name, expected in audit["artifacts"].items():
        if digest(data_dir / name) != expected:
            raise ValueError("A prepared modeling artifact changed: " + name)
    for name, expected in audit["source_code_sha256"].items():
        if digest(root / name) != expected:
            raise ValueError("Source changed after preparation; create a fresh prepared run: " + name)
    features = pd.read_parquet(data_dir / "features.parquet")
    metadata = pd.read_parquet(data_dir / "metadata.parquet").loc[features.index]
    for column in CATEGORICAL:
        features[column] = features[column].astype(object)
    indices, cohorts = {}, {}
    for name in ["selection_train", "selection_validation", "final_refit", "calibration_and_threshold_development", "holdout_test"]:
        indices[name], cohorts[name] = mature_window(metadata, protocol[name])
    fitting, validation = indices["selection_train"], indices["selection_validation"]
    refit, calibration, test = [indices[name] for name in ["final_refit", "calibration_and_threshold_development", "holdout_test"]]
    assert set(refit).isdisjoint(calibration) and set(refit).isdisjoint(test) and set(calibration).isdisjoint(test)
    assert set(fitting).isdisjoint(validation)
    selection, recorded_warnings = [], []
    model_directory = root / "models" / run_id
    model_directory.mkdir(parents=True, exist_ok=False)
    y_train = metadata.loc[fitting, "target"].to_numpy(dtype=int)
    y_validation = metadata.loc[validation, "target"].to_numpy(dtype=int)
    for specification in protocol["candidates"]:
        tick = time.perf_counter()
        estimator = make_estimator(specification, protocol["seed"])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            estimator.fit(features.loc[fitting], y_train)
        recorded_warnings.extend({"candidate": specification["name"], "message": str(item.message), "category": item.category.__name__} for item in caught)
        probability = estimator.predict_proba(features.loc[validation])[:, 1]
        result = evaluate(y_validation, probability, validation)
        result.update({"candidate": specification["name"], "family": specification["family"],
                       "history": specification["history"], "fit_seconds": round(time.perf_counter() - tick, 3)})
        selection.append(result)
        joblib.dump(estimator, model_directory / ("selection_" + specification["name"] + ".joblib"), compress=3)
        log(f"Validation {specification['name']}: AP={result['average_precision']:.4f}, ROC-AUC={result['roc_auc']:.4f}")
    best = max(selection, key=lambda item: item[protocol["selection_metric"]])
    specification = next(item for item in protocol["candidates"] if item["name"] == best["candidate"])
    write_json(run_dir / "selection_results.json", selection)
    pd.DataFrame([{key: item[key] for key in ["candidate", "average_precision", "roc_auc", "brier_score", "fit_seconds"]} for item in selection]).to_csv(run_dir / "selection_results.csv", index=False)
    write_json(run_dir / "selection_lock.json", {"selected_at": datetime.now().astimezone().isoformat(),
        "candidate": specification, "criterion": "Largest selection-validation average precision only",
        "protocol_sha256": audit["protocol_sha256"], "holdout_evaluated_before_lock": False})
    log("Model selection locked: " + specification["name"] + ". Refitting before later calibration/test periods.")
    final = make_estimator(specification, protocol["seed"])
    final.fit(features.loc[refit], metadata.loc[refit, "target"].to_numpy(dtype=int))
    cal_labels = metadata.loc[calibration, "target"].to_numpy(dtype=int)
    raw_cal = final.predict_proba(features.loc[calibration])[:, 1]
    calibrator = fit_sigmoid(raw_cal, cal_labels)
    cal_probability = calibrator.predict_proba(log_odds(raw_cal))[:, 1]
    threshold = f2_threshold(cal_labels, cal_probability)
    bundle = DeliveryRiskModel(final, calibrator, threshold, {
        "run_id": run_id, "candidate": specification["name"], "feature_version": FEATURE_VERSION,
        "features": FEATURES, "protocol_sha256": audit["protocol_sha256"],
        "simulated_base_fit_cutoff": protocol["final_refit"]["outcomes_before"],
        "simulated_deployment_cutoff": protocol["calibration_and_threshold_development"]["outcomes_before"],
        "trained_at": datetime.now().astimezone().isoformat(),
    })
    model_file = model_directory / "delivery_risk.joblib"
    joblib.dump(bundle, model_file, compress=3)
    write_json(run_dir / "calibration_lock.json", {"locked_at": datetime.now().astimezone().isoformat(),
        "method": "Predeclared sigmoid calibration", "slope": float(calibrator.coef_[0, 0]),
        "intercept": float(calibrator.intercept_[0]), "f2_diagnostic_threshold": threshold,
        "orders": len(calibration), "late_orders": int(cal_labels.sum()), "holdout_evaluated_before_lock": False})
    # Only now evaluate the test cohort. Its labels never choose the preceding objects.
    log("Model and calibration locked. Evaluating the newer August holdout once.")
    test_features = features.loc[test]
    labels = metadata.loc[test, "target"].to_numpy(dtype=int)
    raw_probability = final.predict_proba(test_features)[:, 1]
    probability = bundle.predict_proba(test_features)[:, 1]
    holdout = evaluate(labels, probability, test, threshold)
    raw_metrics = evaluate(labels, raw_probability, test, 0.5)
    constant_probability = np.full(len(test), cal_labels.mean())
    constant = evaluate(labels, constant_probability, test, threshold)
    rolling_probability = test_features["global_late_rate_90d"].to_numpy()
    rolling = evaluate(labels, rolling_probability, test, threshold)
    static_specification = next(item for item in protocol["candidates"] if item["name"] == "logistic_static")
    if specification["name"] == "logistic_static":
        static = final
        static_calibrator = calibrator
    else:
        static = make_estimator(static_specification, protocol["seed"])
        static.fit(features.loc[refit], metadata.loc[refit, "target"].to_numpy(dtype=int))
        static_calibrator = fit_sigmoid(static.predict_proba(features.loc[calibration])[:, 1], cal_labels)
    baseline_probability = static_calibrator.predict_proba(log_odds(static.predict_proba(test_features)[:, 1]))[:, 1]
    static_metrics = evaluate(labels, baseline_probability, test, threshold)
    intervals = day_block_intervals(labels, probability, test, metadata.loc[test, "approved_at"].to_numpy(dtype="datetime64[D]"),
                                   protocol["bootstrap"]["repetitions"], protocol["seed"])
    bins = calibration_bins(labels, probability)
    bins.to_csv(run_dir / "calibration_bins.csv", index=False)
    predictions = metadata.loc[test, ["approved_at", "target"]].copy()
    predictions["raw_probability"] = raw_probability
    predictions["late_probability"] = probability
    predictions["diagnostic_flag"] = probability >= threshold
    predictions.to_parquet(run_dir / "holdout_predictions.parquet", compression="zstd")
    decision_period = (metadata["approved_at"] >= pd.Timestamp(protocol["holdout_test"]["approval_start"])) & (metadata["approved_at"] < pd.Timestamp(protocol["holdout_test"]["approval_end"]))
    replay_ids = metadata.index[decision_period]
    replay = metadata.loc[replay_ids, ["approved_at", "purchased_at", "promised_at", "order_status"]].copy()
    replay["late_probability"] = bundle.predict_proba(features.loc[replay_ids])[:, 1]
    replay["observed_label_by_cutoff"] = metadata.loc[replay_ids, "target"].where(replay_ids.isin(test)).astype("Int64")
    replay["outcome_evaluable"] = replay_ids.isin(test)
    replay["model_run_id"] = run_id
    replay.to_parquet(data_dir / "risk_scores_august_replay.parquet", compression="zstd")
    log("Computing holdout explanations and day-block uncertainty; these do not change the selected model.")
    importance = permutation_diagnostic(bundle, test_features, labels, protocol["seed"])
    importance.to_csv(run_dir / "holdout_permutation_importance.csv", index=False)
    make_figures(run_dir, labels, probability, raw_probability, baseline_probability, test, bins)
    restored = joblib.load(model_file)
    restored_probability = restored.predict_proba(test_features)[:, 1]
    if not np.allclose(probability, restored_probability, rtol=0, atol=1e-12):
        raise ValueError("Saved model inference differs from the evaluated model.")
    summary = {
        "run_id": run_id, "completed_at": datetime.now().astimezone().isoformat(), "actual_execution": "Local laptop CPU; no Colab or additional cloud training",
        "python": platform.python_version(), "scikit_learn": sklearn.__version__, "pandas": pd.__version__, "numpy": np.__version__,
        "feature_version": FEATURE_VERSION, "feature_count": len(FEATURES), "source_orders": audit["original_orders"],
        "valid_approval_decisions": audit["valid_approval_decisions"], "cohorts": cohorts,
        "selected_candidate": specification, "selection_metric": "Validation average precision", "validation_selected_metrics": best,
        "holdout": holdout, "raw_model_holdout": raw_metrics,
        "baselines": {"calibration_period_constant": constant, "rolling_90d_global_rate": rolling, "static_logistic_sigmoid": static_metrics},
        "holdout_day_block_intervals": intervals,
        "calibration": {"method": "Fixed sigmoid", "slope": float(calibrator.coef_[0, 0]), "intercept": float(calibrator.intercept_[0]),
            "development_late_rate": float(cal_labels.mean()), "diagnostic_threshold": threshold,
            "threshold_objective": "F2 on calibration/development cohort only; no capacity or financial effect assumed",
            "holdout_brier_improved_over_raw": holdout["brier_score"] < raw_metrics["brier_score"]},
        "integrity": {"protocol_sha256": audit["protocol_sha256"], "model_sha256": digest(model_file),
            "model_reload_predictions_match": True, "feature_artifact_hashes_verified": True,
            "source_code_sha256": audit["source_code_sha256"], "future_outcome_fields_in_features": [],
            "all_history_events_strictly_before_approval": True, "holdout_used_for_model_selection": False,
            "explanations_use_holdout_after_model_lock": True},
        "artifacts": {"model": model_file.relative_to(root).as_posix(), "report_directory": run_dir.relative_to(root).as_posix(),
            "feature_directory": data_dir.relative_to(root).as_posix(), "august_replay_scores": (data_dir / "risk_scores_august_replay.parquet").relative_to(root).as_posix()},
        "warnings": recorded_warnings, "elapsed_training_and_evaluation_seconds": round(time.perf_counter() - started, 2),
        "limitations": protocol["as_of_assumptions"] + [protocol["coverage_limit"],
            "Probability calibration can shift under later-period prevalence changes; holdout reliability is reported, not guaranteed.",
            "Top-10-percent capture is a ranking diagnostic within evaluable orders; it is not measured avoided delays or an implemented daily review policy.",
            "Permutation importance is post-hoc and noncausal. It does not select features or trigger holdout-driven retraining.",
            "Day-block intervals preserve within-day clustering but not correlation between successive days."],
    }
    write_json(run_dir / "model_results.json", summary)
    write_json(root / "models/latest_model.json", {"run_id": run_id, "model": summary["artifacts"]["model"], "model_sha256": digest(model_file),
        "report": (run_dir / "model_results.json").relative_to(root).as_posix(), "feature_version": FEATURE_VERSION})
    write_json(root / "reports/modeling/latest_completed.json", summary)
    log(json.dumps({"run_id": run_id, "selected": specification["name"], "holdout": holdout,
                    "intervals": intervals, "model_reload_verified": True,
                    "calibration_improved_brier": summary["calibration"]["holdout_brier_improved_over_raw"]}, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "train", "all"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    root = args.root.resolve()
    with threadpool_limits(limits=4):
        run_id = prepare(root) if args.stage in {"prepare", "all"} else args.run_id
        if args.stage in {"train", "all"}:
            if not run_id:
                raise ValueError("Supply the immutable prepared run ID.")
            train(root, run_id)


if __name__ == "__main__":
    main()
