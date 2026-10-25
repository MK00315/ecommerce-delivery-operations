# Approval-time feature contract

Version 1.0.0. The prediction time is the source order approval timestamp. Source
timestamps are kept as supplied, without inventing a timezone conversion.

The model input has an explicit 45-column allowlist in `delivery_features.py`.
Order/customer/seller identifiers are never fitted inputs. Order IDs only join
artifacts and deterministically break tied ranking scores.

## Basket and reference features

| Group | Fields and interpretation |
| --- | --- |
| Service promise | Remaining days from approval until the end of the promised calendar day; purchase-to-approval hours |
| Basket | Item, distinct seller, distinct product, category and origin-state counts |
| Quoted amounts | Item/freight amounts, freight share, value and freight per item; retained in source monetary units |
| Physical catalog | Known total/max item weights and volumes, with separate coverage fractions |
| Geography | Maximum/mean straight-line postcode-centroid distance, distance coverage and known interstate share |
| Calendar | Sine/cosine pairs for approval hour, weekday and month |
| Categories | Customer state, most frequent seller state and most frequent product category; ties resolved alphabetically |

Unknown measurements stay missing rather than turning into zero distance or zero
weight. Logistic models fit median imputation/scaling on their fitting cohort only;
boosted trees handle numeric missing values directly. Category encoders also fit
only the corresponding training cohort and handle previously unseen categories.

These features rely on explicit retrospective assumptions: the final source basket,
quoted freight and promise match their approval-time values, and catalog dimensions
and postcode references were already available. Olist supplies no revision log or
historical catalog versions, so those assumptions cannot be verified from this data.

Payment aggregates are excluded because payment-event timestamps are unavailable.
Final order status, actual delivery, carrier handover, review scores/text and their
derived durations are excluded from the model matrix.

## Observed history

Every history window has the form **[approval minus window, approval)**. An event
at exactly the prediction timestamp is excluded. This also prevents simultaneous
orders from counting one another or an order from counting itself.

- Global delivery histories use completions observed in the preceding 30/90 days.
- Seller outcomes use the preceding 90 days, one event per order/seller pair.
- Demand features count prior approvals over 7/30 days, including orders whose final
  outcome is unknown; they never filter demand by a future delivered status.
- Multiple items from the same seller cannot multiply that seller's order history.
- Order features aggregate distinct sellers by mean/min/max and cold-start share.

The global late-rate prior is `(observed_late + 1) / (observed_completed + 2)`.
This Beta(1,1) prior is fixed before model fitting and does not use the full-data late
rate. A seller's 90-day rate is `(seller_late + 20 * past_global_rate) /
(seller_completed + 20)`. The 20 pseudo-orders are a declared project regularization
choice. New sellers fall back to the past global rate and retain a cold-start flag.

During the August replay, earlier August outcomes may update histories **only after
their recorded completion and strictly before the next prediction**. Fitted model
and calibration parameters remain frozen. This simulates an updating operational
feature store, not a frozen table of whole-test-period seller statistics.

Metadata stores the latest contributing event times for audit. They are not features.
Tests mutate future outcomes and exercise timestamp ties and duplicate item links.

## Label availability and coverage

A valid decision needs a purchase/approval/promise, approval at or after purchase,
an unexpired promised calendar date and a nonempty source basket. This decision
filter uses no delivery, review or final-status information.

A usable training/evaluation outcome additionally needs the existing delivered-order
SLA contract and actual delivery at or after approval. Its completion must be strictly
before the corresponding outcome cutoff in `modeling_protocol.json`. Unknown,
cancelled, incomplete or inconsistent outcomes are never labeled on time.

This target is conditional on valid observed deliveries. Scores on orders with
unobserved or unsupported outcomes have no measured accuracy. Each period reports
the full valid-decision denominator, evaluable count and excluded count. Late arrivals
beyond the stated observation cutoff remain unevaluable and can create selection bias.

## First frozen experiment (archived)

| Purpose | Approval window | Outcome availability cutoff |
| --- | --- | --- |
| Initial training | Before January 2018 | Before February 1, 2018 |
| Candidate selection | February 2018 | Before May 1, 2018 |
| Final refit | Before March 2018 | Before May 1, 2018 |
| Calibration and diagnostic-threshold development | May-June 2018 | Before August 1, 2018 |
| Holdout | August 2018 | Before October 1, 2018 |

The buffers allow outcomes to mature. January enters the final refit after candidate
selection, and March/April/July are not silently assigned to a random split. Their
already observed events can contribute to subsequent history. The experiment does
not impose a row cap. These dates simulate historical availability; actual model
training takes place now on the laptop.

Candidates are selected by February average precision. The selected estimator is
refitted, its probabilities receive one predeclared sigmoid adjustment, and its F2
diagnostic threshold is set on the calibration/development period. That period is
development data, not an unbiased calibration test. August is evaluated afterwards;
its results cannot choose features, hyperparameters, calibration method or threshold.

The top-10-percent capture metric is a ranking diagnostic on evaluable holdout orders.
It is not an implemented daily staffing policy or evidence that delays were prevented.

The first prototype selected a model on February validation but its independent
August test was close to random ranking. It is retained as a failed experiment,
including its source snapshot, model and predictions. Its validation result is not
presented as successful generalization.

## Updated rolling-month development

Modeling protocol version 2.0.0 keeps these same audited feature definitions. It
compares March, April, May and June as separate forward validation months. Every
fold fits only earlier approvals with outcomes observed before that fold begins;
an additional approval-month buffer allows outcomes to mature.

The selection criterion is equal-month mean AP divided by each month's observed
late rate. This compares ranking gains across very different class prevalences.
All development labels must be observed before August 1. The final refit uses
approvals before July 1 and completions before August 1, rather than stopping at
February. Fixed sigmoid calibration and the F2 diagnostic threshold use the chosen
family's May/June out-of-time development predictions. Transferring that calibration
to the more recent final refit is an assumption; measured reliability is reported.

**August has already been inspected. Updated August results are a reused diagnostic,
not a fresh independent test.** Forward validation is also development data used for
selection. New independent future-period validation is unavailable in this dataset.
The updated artifact is for the portfolio research demonstration, not a
production-qualified delivery predictor.

Implementation references: [scikit-learn probability calibration](https://scikit-learn.org/stable/modules/calibration.html),
[histogram gradient boosting](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html)
and [model evaluation](https://scikit-learn.org/stable/modules/model_evaluation.html).
