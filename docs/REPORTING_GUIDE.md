# Delivery reporting: usage and refresh

The Excel workbook and Power BI report use the same verified Olist and operations
snapshots. Reporting includes all 99,441 original orders, with 96,470 SLA-eligible
completed deliveries and 6,534 late deliveries (6.77%). The other 2,971 orders stay
outside the completed delivery-rate denominator. Lateness uses the inclusive
promised calendar date. No rows were sampled for these artifacts.

## Open and use

From the repository root, open:

- `reports/native/Delivery_Operations.xlsx` in Excel.
- `reports/native/Ecommerce_Delivery_Operations.pbix` in Power BI Desktop.
- `powerbi/project/Delivery.pbip` for the editable project source.

The native PBIX already contains its loaded model. It needs no Azure, Databricks
or Power BI Service sign-in to view the local report. The PBIP has portable
embedded snapshot queries; its first opening may require Home > Refresh to load
those queries into the model. The accompanying CSVs are audit/refresh inputs for
the source generator, rather than live linked external files.

## Excel workbook

| Sheet | Use |
|---|---|
| Overview | Formula KPIs, all purchase months, state comparisons and two charts |
| Review capacity | Executed scenarios, four policies, daily detail and a separate staffing calculator |
| Statistics | Four exploratory month-adjusted contrasts and their uncertainty |
| Sources | Five native source tables, typed dates and documented input snapshots |
| ReadMe | Definitions, provenance, instructions and six difference-to-expected controls |

In `Review capacity`, change amber cell C6 to an executed scenario. Cell C7 chooses
the policy for daily detail; the policy comparison above always shows all four
policies under the chosen scenario. The default is `capacity_120_cost_1`, with
721 optimized reviews, 3,314 minutes used, 24 unknown outcomes reviewed and
79 known late outcomes reviewed across 28 batches. The 60-minute scenario gives
378 optimized reviews; the zero-minute scenario gives zero reviews.

Amber K25:K27 are a separate uniform-time calculator: pooled minutes, minutes per
review and review-count limit. K29 returns the smaller of the count limit and
the whole-number minutes bound. Defaults 120 / 4 / 30 produce 30. This calculator
does not account for per-seller constraints or varying review times and does not
rerun the optimizer. Workbook summaries use formulas and SUMIFS, not PivotTables.
Source tabs and formulas should be preserved when exploring input cells.

## Power BI report

| Page | Use |
|---|---|
| Overview | Source totals, late trend, monthly denominator and customer-state filter |
| Delivery patterns | Distance/basket groups, geocoding coverage and state outcomes |
| Review planning | Seven saved scenarios, equally constrained policy comparisons and daily optimized queues |
| Model and statistics | Fixed model evidence, month-adjusted contrasts, methods and limitations |

Use the bottom tabs to change pages. In Desktop edit mode, hold Ctrl while clicking
a top page-navigation button. State slicers apply on their operational page;
select one state or clear the filter for the full dataset. Model/statistical
evidence is fixed and is not re-estimated by these page filters.

On Review planning, choose one executed scenario from the dropdown. The native
PBIX opens with `120 min / 1.00x time` selected; an unfiltered source report uses
that scenario as its DAX default. Scenario selection reads saved optimizer runs;
it does not execute Python, train the model or call Azure. The daily fact is
separate from order rows to prevent multiplication of the planning counts. The
known-late denominator is counted once per batch rather than once per policy.

## Evidence and interpretation

All five Excel sheets and all four Power BI pages were visually reviewed.
The native applications opened and saved the files. Excel scenario recalculation
was checked at 120, 60 and zero minutes; Power BI zero/default selection also
updated the visuals. Nine read-only native DAX queries checked counts, date/state
relationships, scenarios, policies, statistics and model metrics. The saved PBIX
archive contains a loaded DataModel, four pages and 52 native visual elements.
Report source schema validation and archive CRC checks passed. The current full
project suite passed all 62 tests.

The model remains experimental: updated August results reuse an inspected period,
ranking gain is modest and probability reliability is weak. The planning objective
allocates ordinal priority under illustrative time/count/seller limits. Reviewed
known late outcomes are retrospective evidence, not prevented delays or savings.
The statistical contrasts are exploratory associations; intervals are marginal
95% purchase-week clustered intervals, while p values use Holm correction.

Actual cloud ingestion was Azure Data Factory > Azure bronze > verified local
handoff > Databricks Free Edition Delta tables. Model training, statistics and
planning ran locally. These reports are offline snapshots and have no live
Azure/Databricks connector or automatic cloud refresh. No additional cloud run,
retraining or Power BI Service publication was needed for this reporting stage.

## Refresh deliberately

Preserve the delivered workbook/PBIX before rebuilding: source generation replaces
the files at their configured output paths. From the project environment, run
`reporting_data.py` to read the verified DuckDB and completed operations results.
Then run `excel/build_workbook.mjs` with the bundled Artifact Tool Node runtime and
`powerbi/build_report.py` with project Python. The Excel builder requires
`@oai/artifact-tool` from the installed bundled dependencies.

Open the generated Excel file, recalculate, restore defaults and save it. Open
the generated PBIP in Desktop, refresh the embedded queries, review all pages
and Save As a PBIX. Re-run `excel/verify_workbook.py`, report schema validation,
and `powerbi/verify_native_model.ps1 -DesktopProcessId <the intended Desktop PID>`.
That PowerShell verifier only reads the engine belonging to the selected process.
`powerbi/build_report.py --layout-only` preserves the imported semantic model
when only report visuals change. Finish with `finalize_reporting.py` to check
artifacts, regenerate the completion record and package the deliverables.

Source provenance is recorded in the reporting manifest and final verification.
Original public data: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce.
Microsoft project-format reference:
https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview.
