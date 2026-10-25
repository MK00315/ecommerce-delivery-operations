# Initial descriptive findings

These findings come from the executed local pipeline on the complete Olist version-2 source. They describe a historical marketplace snapshot and do not establish causal explanations.

1. **6.77% of the usable completed-order cohort arrived late.** There are 6,534 late orders among 96,470 eligible deliveries. The full mart retains all 99,441 source orders, so incomplete orders are not lost or treated as successful deliveries.
2. **The date definition changes the answer materially.** A timestamp comparison produces 7,826 late cases. The promised-calendar-date definition produces 6,534. The difference is 1,292 orders arriving later during the promised day.
3. **Direct joins inflate money.** Joining order items, payments and reviews directly produces 119,143 rows and item value 14,273,699.65. The source item value is 13,591,643.70. The implemented order mart aggregates the separate child tables first and preserves the original totals exactly.
4. **Review IDs cannot be treated as globally unique.** The review source has 814 extra uses of review IDs across orders, while `(order_id, review_id)` is unique. There are also 551 additional reviews on already-reviewed orders. Those observations are retained; a clearly defined latest-review view is used for order reporting.
5. **Late deliveries are associated with weaker reviews.** Among reviewed eligible orders, low scores occur in 62.42% of late cases and 9.27% of on-time cases. These are associations. Formal testing, effect sizes and dependence/selection limitations belong to the next stage.
6. **Some locations merit investigation.** Rio de Janeiro customers have 1,495 late orders among 12,350 eligible orders (12.11%); Sao Paulo has 1,820 among 40,494 (4.49%). These differences may reflect order mix, geography, timing and seller composition, not a state's causal effect.
7. **Data-quality exceptions stay visible.** Forty-two coordinates outside broad Brazil bounds are excluded from centroids; 1,265 orders lack a known approximate distance. There are 1,382 orders with an invalid sequence in at least one delivery-stage leg. No whole order is deleted solely for these issues.

The next questions are which predictors are available at approval time, how well a model ranks late-delivery risk on later orders, and how to allocate a declared review capacity to the highest-risk cases. The dataset does not observe the effect of the proposed review intervention, so avoided delays and realized savings cannot be claimed.

Executed evidence: `reports/latest_run.json` identifies the versioned run folder containing all 12 SQL CSVs, quality controls and export hashes. Nineteen checks passed, including independent pandas date logic, Decimal money sums, coordinate medians, record preservation and date-boundary cases.
