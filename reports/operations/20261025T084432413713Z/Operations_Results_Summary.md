# Delivery statistics and review-capacity planning

Executed locally on the laptop with Python. This report uses historical public Olist data, not live delivery operations.

## Historical patterns

The source has 99,441 orders. Analysis uses 96,470 eligible completed orders, including 6,534 late orders (6.77%). The other 2,971 orders are outside that outcome denominator.

Each contrast includes purchase-month fixed effects. Uncertainty clusters orders by purchase week; a day-cluster sensitivity is also saved. Differences are in percentage points (pp). These are separate observational contrasts, with no claim that changing an input would cause the reported change.

| Comparison | Reference late rate | Exposed late rate | Month-adjusted difference (95% interval) | Holm p | Contrast exclusions |
|---|---:|---:|---:|---:|---:|
| Distance >1,000 km vs <=500 km | 5.58% (54,758) | 10.39% (15,390) | +4.89 pp (+3.35, +6.44) | 4.37e-08 | 26,322 |
| Two or more items vs one item | 6.94% (86,835) | 5.29% (9,635) | -1.73 pp (-2.42, -1.03) | 1.01e-05 | 0 |
| Promise <=14 days vs >14 days | 6.85% (84,468) | 6.21% (12,002) | -0.92 pp (-3.98, +2.14) | 0.551 | 0 |
| Any interstate seller vs all same-state | 4.52% (34,575) | 8.03% (61,895) | +3.48 pp (+1.73, +5.22) | 0.000298 | 0 |

The four two-sided primary p-values use Holm family-wise correction. Displayed 95% intervals are marginal, not simultaneous. Thresholds were fixed for this exploratory analysis after earlier data inspection, not preregistered. Week-cluster inference assumes independence across weeks and does not fully account for recurring sellers/customers or longer dependence. Purchase-month adjustment does not eliminate confounding, censoring, selection into completed delivery or snapshot-availability assumptions.

## Review-capacity scenario

The saved model scores cover 6,603 valid August approvals. At 09:00 the next day, 13 orders already have a recorded completed delivery and leave the queue. The remaining 6,590 orders form 28 once-only daily screening batches. Their outcomes are joined only after selection. 103 candidate outcomes remain unknown.

The default assumption is **120 pooled team minutes per batch**, at most **30 reviews** and **5 reviews per primary seller**. A basket takes 4 assumed minutes, plus 2 for multiple items, 3 for multiple sellers and 1 for any interstate/unknown-state movement. These durations are scenario assumptions, not measured staffing data. The primary seller is the most frequent item seller, with seller ID breaking ties; the concentration limit does not cover every seller of a mixed basket.

All approvals are known before the screening cutoff. Only delivery completion recorded before that cutoff can affect eligibility. The solver cannot receive outcomes, final statuses or future timestamps. Within-batch score rank becomes 0-100 ordinal priority points; the full-August percentile is ignored. The optimizer maximizes total points subject to the declared constraints. Points have no probability, avoided-delay or monetary interpretation. Staff minutes are pooled; this is not individual shift scheduling or fleet routing. Unselected orders are not carried over.

| Default policy | Reviewed | Minutes used across all batches | Unknown outcomes reviewed | Known late orders reviewed | Capture of known candidate late orders | Priority points |
|---|---:|---:|---:|---:|---:|---:|
| Constrained optimizer | 721 | 3,314 | 24 | 79 | 19.46% | 63,809.4 |
| Highest risk first | 662 | 3,268 | 20 | 47 | 11.58% | 60,932.6 |
| Priority per minute | 711 | 3,273 | 25 | 78 | 19.21% | 63,159.7 |
| Oldest approval first | 696 | 3,275 | 9 | 42 | 10.34% | 36,010.9 |

The optimizer's objective is ordinal priority allocation, not maximizing known historical late counts. It reviews 721 orders and encounters 79 known late outcomes; highest-risk-first encounters 47. Actual late counts can differ from the score objective. No policy is selected or tuned using these retrospective outcomes.

Sensitivity covers 0, 60, 120, 180 and 240 minutes per batch and 0.75x/1x/1.25x duration assumptions (rounded up to whole minutes). Every baseline uses the same limits. Optimization status/gap is recorded per batch; a time-limited feasible solution is never labelled optimal. No budget violation is accepted.

The original model failed its first independent August test. The updated model and this planner reuse August as a diagnostic. Absolute model probabilities are unreliable and ranking gains modest. This replay is not independent new-period validation, evidence of causal impact, prevented delays, savings or a production-ready decision system.

## Files and verification

- `statistical_contrasts.csv`: group counts, rates, adjusted differences, week/day intervals and Holm p-values.
- `descriptive_groups.csv`: complete partitions by state, distance, basket, promise and purchase month; small groups flagged.
- `scenario_summary.csv` / `daily_policy_results.csv`: all policies, capacities, time assumptions and solver status.
- Private versioned run: `review_candidates.parquet`, `selected_orders.parquet`, archived protocol/code and source hashes. These order-level outputs remain excluded from Git.
- `Verification.json`: independent reconciliations and tests, produced after the run.

Methods: [SciPy mixed-integer solver](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html), [CR1 clustered covariance reference](https://www.statsmodels.org/stable/generated/statsmodels.stats.sandwich_covariance.cov_cluster.html), [Holm correction reference](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html). CR1/FWL and Holm are implemented with NumPy/SciPy; the statsmodels package is not required.

Run: `20261025T084432413713Z`. Source/model hashes and the frozen protocol are retained in the run manifest.
