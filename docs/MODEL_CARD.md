# Delivery risk model: training and evaluation record

Modeling version 2.0.0; actual local execution completed 2026-10-25T02:22:05.947291+05:30.
Run `20261024T205105365739Z_rolling`. **This is an experimental review-priority model.**

## What was built

All 99,441 source orders were considered without a row cap. The approval-time feature
pipeline produced 98,647 valid decisions and 45 prepared inputs.
Six candidate configurations were compared across four forward validation months.
Logistic regression with the static basket/reference features was selected by the
predeclared equal-month AP-to-prevalence criterion, then refitted on
83,848 mature observed orders.
The selected estimator uses 31 inputs; the additional strictly historical
seller/demand features were engineered and tested but did not win this comparison.

Selection, feature encoding, calibration and threshold development use only data
available before the simulated August 1 deployment. The actual training was done now
on the laptop, not historically in 2018. No Colab or additional cloud training ran.

## The first test failed, and remains visible

The first prototype selected boosted trees on February validation. Its independent
August test produced AP 0.0644 and ROC-AUC 0.5072,
close to random ranking. That model, source snapshot, predictions and result were
preserved and rejected for poor generalization.

The updated rolling-month protocol was developed afterwards. **August has already
been inspected: updated August results are a reused diagnostic, not a fresh independent
test.** The forward folds are development data used for candidate selection. There is
no new independent future-period test for the updated model in this dataset.

## Forward development results

Each fold fits only earlier approvals with completions observed before that month
begins. A preceding approval-month buffer allows outcomes to mature. Validation
outcomes must be observed before August 1. Dates and configurations were frozen before
the rolling comparison in `modeling_protocol_rolling.json`.

| Month | Evaluable orders | Late rate | AP | ROC-AUC | AP / late rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| March | 7,083 | 19.20% | 0.3529 | 0.6825 | 1.84 |
| April | 6,623 | 4.61% | 0.1645 | 0.7799 | 3.57 |
| May | 6,938 | 6.51% | 0.1575 | 0.7463 | 2.42 |
| June | 6,068 | 0.84% | 0.0870 | 0.7863 | 10.35 |

| Candidate | Equal-month mean AP / late rate | Mean ROC-AUC |
| --- | ---: | ---: |
| logistic_static | 4.54 | 0.7487 |
| logistic_history | 3.55 | 0.7576 |
| boosted_15 | 3.38 | 0.7081 |
| boosted_static_15 | 2.75 | 0.7171 |
| boosted_31 | 2.53 | 0.6914 |
| constant_prior | 1.00 | 0.5000 |

The criterion gives each month equal weight and divides AP by its observed late
rate. June has few positives and a much lower late rate, so a large June ratio
should not be read as a guaranteed gain in another month. These are model-selection
estimates, not independent test scores.

## August reused diagnostic: modest ranking benefit

Of 6,603 valid approval decisions,
6,495 have evaluable outcomes by October 1 (98.36% coverage).
The other 108 outcomes are not treated as on time. There are 406
observed late deliveries, an observed late rate of 6.25%.

| Measure | Result |
| --- | ---: |
| Average precision (AP) | 0.0901 |
| Constant-score AP reference | 0.0625 |
| ROC-AUC | 0.6177 |
| Reviewed in top-10% diagnostic | 650 |
| Known late orders captured | 59 of 406 |
| Late recall in top 10% | 14.53% |
| Precision in top 10% | 9.08% |
| Ranking lift over observed prevalence | 1.45x |

This is a modest improvement in retrospective ranking, not strong operational
prediction. A 400-repeat bootstrap over 28
approval days gives a top-10% recall interval of
10.37%-19.70%.
That interval describes the fixed diagnostic predictions, does not account for
test reuse/model selection, and does not model dependence between successive days.

## Probability reliability did not improve

A fixed sigmoid was fitted to May/June out-of-time development predictions. Its
transfer to the recent final refit was not successful on the August diagnostic.
Lower Brier score is better: sigmoid-adjusted 0.06087, raw model
0.05930, constant calibration-period rate
0.05917.

Absolute probability reliability is therefore not claimed. The saved replay provides
an experimental **review-priority rank and percentile**. Raw and sigmoid scores remain
available for diagnosis and have identical order ranking. The F2 threshold was fitted
on development data; it is not a staffing limit, cost optimum or recommended
automatic decision rule. No claim of prevented delays or financial savings is made.

## Temporal and artifact verification

- Explicit feature allowlist; current delivery, carrier handover, reviews, final
  status, payment aggregates and identifiers cannot be fitted inputs.
- History includes only events strictly before approval, including exclusion of
  timestamp ties. Future outcomes and duplicate item links are tested.
- Independent direct SQL checked 14 history values for each of 50 real orders,
  including multi-seller orders: all 700 comparisons matched.
- All 40 local tests passed, with no failures or skips; Python lint passed.
- Source feature and archived training-code hashes were checked. Reloaded model
  probabilities match all 6,495 recorded diagnostic predictions.
- Unknown-category and missing-numeric inference passed. The selected model and all
  original experiments remain separately versioned.

## Limits and next use

The target is conditional on usable completed deliveries before stated cutoffs.
Accuracy for cancelled, unfinished or inconsistent outcomes is not measured. Source
basket/freight/promise values and catalog/geography references are assumed available
at approval because Olist has no revision history. See `FEATURE_CONTRACT.md`.

The artifact is suitable for a transparent portfolio replay of review prioritization.
It is not production-qualified. New untouched-period evidence and improved probability
reliability are required before business decisions. Statistical hypothesis analysis,
capacity-constrained scenario planning, Excel, Power BI, the professional dashboard
and publication are still subsequent stages.

Reproduce the current experiment with `train_delivery_model.py prepare`,
`audit_delivery_history.py --run-id <prepared-run-id>` and
`train_delivery_rolling.py --feature-run <prepared-run-id>`. The first protocol and
its failed independent test remain archived under the feature run. Saved artifacts
are located through `models/latest_model.json` and `reports/modeling/latest_completed.json`.

Method references: [scikit-learn probability calibration](https://scikit-learn.org/stable/modules/calibration.html)
and [classification metrics](https://scikit-learn.org/stable/modules/model_evaluation.html).
