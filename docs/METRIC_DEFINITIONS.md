# Metrics and data contracts

## Table grains

- `gold.orders`: exactly one row for each source order, including cancelled and unfinished orders.
- `gold.order_items`: one source `(order_id, item_number)` pair. An item line is not an order.
- `gold.order_sellers`: one `(order_id, seller_id)` pair. It reports sellers associated with an order's outcome; it cannot establish which seller caused a delay.
- `silver.reviews`: every source `(order_id, review_id)` pair. A review ID alone is not a unique key in this dataset.
- `silver.latest_reviews`: one review per order, selected by latest answer timestamp, then creation timestamp, then review ID. Selection is only for descriptive reporting, not model input.
- `silver.postcodes`: one postcode prefix, using median coordinates after excluding points outside latitude -34 to 6 and longitude -74 to -34. Original points remain in the raw table.

## Delivery reporting

SLA eligibility requires final status `delivered`, valid purchase/estimated/customer-delivery timestamps, delivery at or after purchase, and a promised calendar date at or after the purchase date. The completed historical cohort has 96,470 orders. Eight records marked delivered lack their customer-delivery timestamp and remain outside this denominator.

`is_late` is true when the actual customer-delivery **calendar date** exceeds the estimated delivery calendar date. Arrival at 23:59 on the promised day is on time. `is_late` is null for ineligible orders; missing or unresolved outcomes are never silently counted as on time.

`late_calendar_days` counts calendar boundaries beyond the promise and is zero for an on-time eligible order. `delivery_days` is elapsed timestamp duration divided by 86,400 seconds. Those units intentionally differ. Source timestamps have no supplied timezone offset and are preserved as given; no invented UTC conversion is applied.

Approval, seller-handling and carrier-transit durations have separate known/valid denominators. A negative leg duration is null in that leg's KPI and flagged as an invalid stage sequence. The order remains in the mart. Medians of separate stages are not additive.

The snapshot contains unfinished orders; they are not described as still open today. Delivery analysis concerns completed orders with known outcomes, which may differ from cancelled or unobserved orders.

## Money

Money is stored as exact two-decimal `DECIMAL` values and reconciled independently against the source. Item value, recorded freight value and recorded payment value are separate measures. Payment sums need not equal item plus freight sums in every order; differences are not overwritten or called accounting errors without further evidence.

The source has no explicit currency column. Values are retained in source monetary units with no FX conversion. Any future BRL label will be documented as a Brazil-dataset reporting assumption rather than a currency field read from the files. Item value is not Olist's net revenue, and recorded freight is not established as the carrier's actual expense.

## Geography and categories

Distance is the great-circle distance between seller and customer postcode centroids, using Earth radius 6,371.0088 km. It is not a driven route, exact street address or measured travel time. Missing coordinates stay unknown. Order-level maximum distance describes the farthest known seller approximation; incomplete item coverage remains visible.

Product-category lateness is item weighted, with an explicit eligible-item denominator. A mixed-category order can appear under several categories. Category distinct-order counts and seller-associated order counts must not be added to reproduce a unique-order total.

Review analysis uses the latest known review per order and excludes unreviewed orders from review-score percentages. Low review means score 1 or 2 out of 5. Associations are descriptive and do not establish causal effects.

## Implemented prediction contract

The decision time is **order approval**. Actual delivery, carrier handover, review scores, final status and payment aggregates are excluded from prediction inputs. Seller-history features use only completions already observed strictly before each order's approval time, including exclusion of timestamp ties. Basket, promise and catalog dimensions are final-snapshot attributes whose approval-time availability remains an explicit assumption.

Forty-five inputs are prepared; the selected static logistic model uses 31. Its final
refit has 83,848 mature observed orders. March-June forward folds select the candidate,
and May/June out-of-time development predictions fit a fixed sigmoid and F2 diagnostic
threshold. The first independent August test failed and remains archived. Updated
August figures are reused diagnostics, not an untouched test of the new scheme.

Evaluation reports AP, ROC-AUC, Brier/log loss, late precision/recall, coverage and
top-10-percent capture. Accuracy alone would reward an unhelpful always-on-time rule.
Updated August top-10-percent capture is 14.53% of known late orders, a modest gain.
Probability reliability did not improve over raw or constant predictions, so replay
outputs are experimental priority ranks rather than established absolute risk.

Outcome cutoffs exclude unfinished, inconsistent and later-completing labels without
calling them on time. August has 6,603 valid decisions and 6,495 evaluable outcomes;
108 outcomes remain unevaluable. The conditional observed-delivery target does not
establish accuracy on cancelled or unfinished orders. See `FEATURE_CONTRACT.md` and
`MODEL_CARD.md` for chronology, transfer assumptions and the retained failure.

## Statistical association contract

The statistical cohort is the 96,470 SLA-eligible completed orders. Separate binary
contrasts compare distance >1,000 vs <=500 km (complete geocoding only, middle band
excluded), 2+ vs 1 item, purchase-to-promise <=14 vs >14 days, and any interstate
seller vs all same-state (complete state coverage). Each reports its own exclusions.

A linear probability contrast with purchase-month fixed effects estimates an
adjusted percentage-point association. CR1 uncertainty clusters by purchase week
(Monday-Sunday); two-sided Student t inference uses cluster-count minus one degrees
of freedom. Purchase-day clustered intervals are a sensitivity check. Holm adjusts
the four primary week-clustered p-values; displayed 95% intervals are marginal.
This is exploratory work after prior inspection. Thresholds are not preregistered,
monthly effects do not eliminate confounding, and longer serial/repeated-entity
dependence and completed-outcome selection remain limitations.

## Review scenario contract

Each valid August approval enters one screening batch at 09:00 the next calendar
day. Deliveries already recorded strictly before screening are removed; source
timestamps are kept as provided. A delivery at the cutoff is excluded from that
known-event filter. Final status and unknown/future lateness never determine
selection. Unselected work leaves the simulation without carryover.

The model supplies ranking only. Priority points are `100*(n-rank+1)/n` within the
current candidate batch, with raw score descending and order ID as tie-breaker.
The whole-August percentile is not an input. Review minutes are an explicit scenario
assumption: 4 base, +2 for multiple items, +3 for multiple sellers, +1 for any
interstate or incomplete/unknown state coverage. Sensitivity scales and rounds up
these assumed times. Minutes are pooled, not individually scheduled staff shifts.

Binary decisions maximize summed priority points under time, count and primary-
seller caps. The primary seller is the most frequent item seller, then smallest
seller ID on ties. A mixed basket's other sellers are not covered by this cap.
Every comparison queue uses the same limits. Solver optimality applies to this
declared ordinal objective, not to actual lateness, fairness, delivery routes or
financial benefit.

Known late capture is selected known-late orders divided by all known-late candidate
orders (406 in this replay). Unknown selected outcomes remain a separate count and
consume time; observed precision divides only by selected *known* outcomes and
does not imply performance on unknown outcomes. Scores were generated at approval;
nullable outcomes are attached solely after selection for retrospective reporting.
The reused-August and unreliable-probability restrictions continue to apply.
