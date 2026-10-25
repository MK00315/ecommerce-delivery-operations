"""Forward-month development and a recent refit; August is a reused diagnostic."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import warnings

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from delivery_features import CATEGORICAL, FEATURES, FEATURE_VERSION, digest, mature_window
from delivery_pipeline import write_json
from delivery_risk import DeliveryRiskModel, day_block_intervals, evaluate, f2_threshold, fit_sigmoid, log_odds, make_estimator
from train_delivery_model import calibration_bins, log, make_figures, permutation_diagnostic

ROOT = Path(__file__).resolve().parent


def assert_protocol(protocol):
    cutoff = pd.Timestamp(protocol["development_outcomes_before"])
    for fold in protocol["folds"]:
        assert pd.Timestamp(fold["fit_approval_end"]) < pd.Timestamp(fold["validation_start"])
        assert pd.Timestamp(fold["fit_outcomes_before"]) <= pd.Timestamp(fold["validation_start"])
        assert pd.Timestamp(fold["validation_end"]) <= cutoff
    assert pd.Timestamp(protocol["final_refit"]["outcomes_before"]) <= pd.Timestamp(protocol["august_replay"]["approval_start"])
    assert pd.Timestamp(protocol["final_refit"]["approval_end"]) <= cutoff
    assert pd.Timestamp(protocol["final_refit"]["outcomes_before"]) <= cutoff
    assert not protocol["independent_future_validation_available"]


def run(root, feature_run):
    started = time.perf_counter()
    protocol_path = root / "modeling_protocol_rolling.json"
    protocol = json.loads(protocol_path.read_text())
    assert_protocol(protocol)
    parent = root / "reports/modeling" / feature_run
    audit = json.loads((parent / "feature_audit.json").read_text())
    data_dir = root / audit["data_directory"]
    for filename, expected in audit["artifacts"].items():
        if digest(data_dir / filename) != expected:
            raise ValueError("Prepared feature/metadata artifact changed.")
    for source in ["delivery_features.py", "delivery_risk.py"]:
        if digest(root / source) != audit["source_code_sha256"][source]:
            raise ValueError("Feature or estimator implementation differs from the audited source.")
    features = pd.read_parquet(data_dir / "features.parquet")
    metadata = pd.read_parquet(data_dir / "metadata.parquet").loc[features.index]
    for column in CATEGORICAL:
        features[column] = features[column].astype(object)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_rolling"
    run_dir = root / "reports/modeling" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    model_dir = root / "models" / run_id
    model_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "protocol.json").write_bytes(protocol_path.read_bytes())
    snapshots = run_dir / "source_snapshot"
    snapshots.mkdir()
    source_names = ["delivery_features.py", "delivery_risk.py", "train_delivery_model.py", "train_delivery_rolling.py", "modeling_protocol_rolling.json"]
    hashes = {}
    for name in source_names:
        (snapshots / name).write_bytes((root / name).read_bytes())
        hashes[name] = digest(root / name)
    (run_dir / "independent_history_audit.json").write_bytes((parent / "independent_history_audit.json").read_bytes())
    write_json(run_dir / "feature_provenance.json", {"feature_run": feature_run, "feature_audit": audit,
        "feature_contract_unchanged_from_first_prototype": True, "source_code_sha256": hashes})
    cohort_rows, fold_data = {}, []
    for fold in protocol["folds"]:
        fit_spec = {"approval_start": "2016-01-01", "approval_end": fold["fit_approval_end"], "outcomes_before": fold["fit_outcomes_before"]}
        val_spec = {"approval_start": fold["validation_start"], "approval_end": fold["validation_end"], "outcomes_before": protocol["development_outcomes_before"]}
        fit_ids, fit_coverage = mature_window(metadata, fit_spec)
        val_ids, val_coverage = mature_window(metadata, val_spec)
        assert set(fit_ids).isdisjoint(val_ids)
        assert (metadata.loc[fit_ids, "delivered_at"] < pd.Timestamp(fold["validation_start"])).all()
        cohort_rows[fold["name"]] = {"fit": fit_coverage, "validation": val_coverage}
        fold_data.append((fold, fit_ids, val_ids))
    write_json(run_dir / "fold_cohorts.json", cohort_rows)
    results, predictions, captured_warnings = [], {}, []
    for specification in protocol["candidates"]:
        candidate_rows = []
        for fold, fit_ids, val_ids in fold_data:
            estimator = make_estimator(specification, protocol["seed"])
            y_fit = metadata.loc[fit_ids, "target"].to_numpy(dtype=int)
            y_val = metadata.loc[val_ids, "target"].to_numpy(dtype=int)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                estimator.fit(features.loc[fit_ids], y_fit)
            captured_warnings.extend({"candidate": specification["name"], "fold": fold["name"], "message": str(item.message)} for item in caught)
            raw = estimator.predict_proba(features.loc[val_ids])[:, 1]
            metrics = evaluate(y_val, raw, val_ids)
            lift = metrics["average_precision"] / metrics["late_rate"]
            results.append({"candidate": specification["name"], "fold": fold["name"], **metrics, "ap_over_prevalence": lift})
            table = pd.DataFrame({"fold": fold["name"], "target": y_val, "raw_probability": raw}, index=val_ids)
            candidate_rows.append(table)
            log(f"{specification['name']} / {fold['name']}: AP={metrics['average_precision']:.4f}, AP/prevalence={lift:.2f}")
        predictions[specification["name"]] = pd.concat(candidate_rows)
        predictions[specification["name"]].to_parquet(run_dir / (specification["name"] + "_development_predictions.parquet"), compression="zstd")
    comparison = pd.DataFrame([{key: item[key] for key in ["candidate", "fold", "orders", "late_orders", "late_rate", "average_precision", "roc_auc", "ap_over_prevalence"]} for item in results])
    comparison.to_csv(run_dir / "forward_fold_metrics.csv", index=False)
    means = comparison.groupby("candidate", sort=False).agg(
        mean_ap_over_prevalence=("ap_over_prevalence", "mean"), mean_average_precision=("average_precision", "mean"),
        mean_roc_auc=("roc_auc", "mean"), minimum_ap_over_prevalence=("ap_over_prevalence", "min"),
    ).reset_index()
    means.to_csv(run_dir / "candidate_comparison.csv", index=False)
    selected_name = str(means.iloc[int(means["mean_ap_over_prevalence"].to_numpy().argmax())]["candidate"])
    selected_spec = next(item for item in protocol["candidates"] if item["name"] == selected_name)
    write_json(run_dir / "selection_lock.json", {"locked_at": datetime.now().astimezone().isoformat(),
        "candidate": selected_spec, "criterion": protocol["selection_metric"], "august_used_in_selection": False,
        "august_status": protocol["august_status"], "protocol_sha256": digest(run_dir / "protocol.json")})
    log("Rolling-month model selection locked: " + selected_name)
    selected_predictions = predictions[selected_name]
    calibration_rows = selected_predictions.loc[selected_predictions["fold"].isin(["May", "June"])]
    cal_labels = calibration_rows["target"].to_numpy(dtype=int)
    calibrator = fit_sigmoid(calibration_rows["raw_probability"], cal_labels)
    cal_probability = calibrator.predict_proba(log_odds(calibration_rows["raw_probability"]))[:, 1]
    threshold = f2_threshold(cal_labels, cal_probability)
    final_ids, final_coverage = mature_window(metadata, protocol["final_refit"])
    final = make_estimator(selected_spec, protocol["seed"])
    final.fit(features.loc[final_ids], metadata.loc[final_ids, "target"].to_numpy(dtype=int))
    bundle = DeliveryRiskModel(final, calibrator, threshold, {"run_id": run_id, "modeling_version": protocol["version"],
        "candidate": selected_name, "feature_version": FEATURE_VERSION, "features": FEATURES,
        "protocol_sha256": digest(run_dir / "protocol.json"), "simulated_deployment_cutoff": "2018-08-01",
        "trained_at": datetime.now().astimezone().isoformat(), "august_evaluation": "Reused diagnostic",
        "production_qualified": False})
    model_path = model_dir / "delivery_risk.joblib"
    joblib.dump(bundle, model_path, compress=3)
    write_json(run_dir / "calibration_lock.json", {"locked_at": datetime.now().astimezone().isoformat(),
        "source": "May/June out-of-time development predictions", "orders": len(calibration_rows),
        "slope": float(calibrator.coef_[0, 0]), "intercept": float(calibrator.intercept_[0]),
        "threshold": threshold, "august_used": False})
    # The August diagnostic starts only after the candidate/calibrator/threshold locks.
    august, august_coverage = mature_window(metadata, protocol["august_replay"])
    assert set(final_ids).isdisjoint(august)
    y_august = metadata.loc[august, "target"].to_numpy(dtype=int)
    raw_august = final.predict_proba(features.loc[august])[:, 1]
    p_august = bundle.predict_proba(features.loc[august])[:, 1]
    august_metrics = evaluate(y_august, p_august, august, threshold)
    raw_metrics = evaluate(y_august, raw_august, august)
    static_spec = next(item for item in protocol["candidates"] if item["name"] == "logistic_static")
    static_development = predictions["logistic_static"]
    static_cal = static_development.loc[static_development["fold"].isin(["May", "June"])]
    static_calibrator = fit_sigmoid(static_cal["raw_probability"], static_cal["target"])
    if selected_name == "logistic_static":
        baseline = final
    else:
        baseline = make_estimator(static_spec, protocol["seed"])
        baseline.fit(features.loc[final_ids], metadata.loc[final_ids, "target"].to_numpy(dtype=int))
    static_august = static_calibrator.predict_proba(log_odds(baseline.predict_proba(features.loc[august])[:, 1]))[:, 1]
    baselines = {"static_logistic": evaluate(y_august, static_august, august, threshold),
                 "constant_calibration_rate": evaluate(y_august, np.full(len(august), cal_labels.mean()), august, threshold)}
    intervals = day_block_intervals(y_august, p_august, august, metadata.loc[august, "approved_at"].to_numpy(dtype="datetime64[D]"),
                                   protocol["bootstrap_repetitions"], protocol["seed"])
    august_table = metadata.loc[august, ["approved_at", "target"]].copy()
    august_table["raw_probability"] = raw_august
    august_table["late_probability"] = p_august
    august_table.to_parquet(run_dir / "august_diagnostic_predictions.parquet", compression="zstd")
    period = ((metadata["approved_at"] >= pd.Timestamp(protocol["august_replay"]["approval_start"]))
              & (metadata["approved_at"] < pd.Timestamp(protocol["august_replay"]["approval_end"])))
    all_ids = metadata.index[period]
    replay = metadata.loc[all_ids, ["approved_at", "purchased_at", "promised_at", "order_status"]].copy()
    replay["late_probability"] = bundle.predict_proba(features.loc[all_ids])[:, 1]
    replay["observed_label_by_cutoff"] = metadata.loc[all_ids, "target"].where(all_ids.isin(august)).astype("Int64")
    replay["outcome_evaluable"] = all_ids.isin(august)
    replay["model_run_id"] = run_id
    replay["evaluation_role"] = "Reused August diagnostic; not an independent new test"
    replay.to_parquet(run_dir / "risk_scores_august_replay.parquet", compression="zstd")
    bins = calibration_bins(y_august, p_august)
    bins.to_csv(run_dir / "august_calibration_bins.csv", index=False)
    importance = permutation_diagnostic(bundle, features.loc[august], y_august, protocol["seed"])
    importance.to_csv(run_dir / "august_diagnostic_permutation_importance.csv", index=False)
    make_figures(run_dir, y_august, p_august, raw_august, static_august, august, bins,
                 evaluation_label="August 2018 reused diagnostic")
    restored = joblib.load(model_path)
    assert np.allclose(restored.predict_proba(features.loc[august])[:, 1], p_august, rtol=0, atol=1e-12)
    original = json.loads((parent / "model_results.json").read_text())
    summary = {"run_id": run_id, "modeling_version": protocol["version"], "completed_at": datetime.now().astimezone().isoformat(),
        "actual_execution": "Local laptop CPU", "feature_version": FEATURE_VERSION, "feature_count": len(FEATURES),
        "feature_run": feature_run, "source_orders": audit["original_orders"], "valid_decisions": audit["valid_approval_decisions"],
        "selection": {"candidate": selected_spec, "criterion": protocol["selection_metric"], "folds": [fold["name"] for fold in protocol["folds"]],
            "comparison": means.to_dict("records"), "fold_metrics": comparison.to_dict("records"), "august_used": False},
        "cohorts": {"forward_folds": cohort_rows, "final_refit": final_coverage, "august_diagnostic": august_coverage},
        "calibration": {"source": "May/June out-of-time development predictions", "orders": len(cal_labels), "late_orders": int(cal_labels.sum()),
            "slope": float(calibrator.coef_[0, 0]), "intercept": float(calibrator.intercept_[0]), "f2_diagnostic_threshold": threshold,
            "august_brier_improved_over_raw": august_metrics["brier_score"] < raw_metrics["brier_score"]},
        "august_diagnostic": august_metrics, "raw_august_diagnostic": raw_metrics, "august_baselines": baselines,
        "august_day_block_intervals": intervals, "august_evaluation_status": protocol["august_status"],
        "first_prototype": {"run_id": feature_run, "candidate": original["selected_candidate"]["name"],
            "independent_august_test": original["holdout"], "status": "Rejected for poor temporal generalization"},
        "independent_new_period_validation_available": False, "production_qualified": False,
        "artifact_status": "Portfolio research model; retain evaluation limitations in reports and UI",
        "verification": {"model_reload_predictions_match": True, "same_audited_feature_artifacts": True,
            "future_outcome_fields_in_features": [], "strict_history_time_checks": True,
            "independent_history_audit": json.loads((parent / "independent_history_audit.json").read_text())},
        "artifacts": {"model": model_path.relative_to(root).as_posix(), "model_sha256": digest(model_path),
            "report_directory": run_dir.relative_to(root).as_posix(), "feature_directory": audit["data_directory"],
            "august_replay_scores": (run_dir / "risk_scores_august_replay.parquet").relative_to(root).as_posix()},
        "source_code_sha256": hashes, "protocol_sha256": digest(run_dir / "protocol.json"), "warnings": captured_warnings,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "limitations": protocol["constraints"] + [
            "Forward validation scores are development estimates used to select the candidate, not independent test estimates.",
            "OOF sigmoid calibration transfers between month-specific fits and the final refit; reliability under changing prevalence is not guaranteed.",
            "Outcome coverage is conditional on valid completed deliveries before each cutoff; unobserved/cancelled orders have no measured accuracy.",
            "Top-10-percent capture and day-block intervals describe a retrospective ranking diagnostic, not avoided delays or causal savings."]}
    write_json(run_dir / "model_results.json", summary)
    pointer = {"run_id": run_id, "model": summary["artifacts"]["model"], "model_sha256": digest(model_path),
               "report": (run_dir / "model_results.json").relative_to(root).as_posix(), "feature_version": FEATURE_VERSION,
               "status": "Portfolio research model with forward validation; August is a reused diagnostic", "production_qualified": False}
    write_json(root / "models/latest_model.json", pointer)
    write_json(root / "reports/modeling/latest_completed.json", summary)
    log(json.dumps({"run_id": run_id, "selected": selected_name, "candidate_comparison": means.to_dict("records"),
                    "final_fit_orders": len(final_ids), "august_diagnostic": august_metrics,
                    "august_status": protocol["august_status"], "model_reload_verified": True}, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-run", required=True)
    arguments = parser.parse_args()
    with threadpool_limits(limits=4):
        run(ROOT, arguments.feature_run)
