# Project scope and stage record

Business objective: identify patterns in historical delivery performance, estimate lateness risk at approval time, and prioritize a constrained operations review queue. This is a student portfolio demonstration using public historical data, not a live logistics control system.

The supplied Straive Data Analyst Trainee description emphasizes problem structuring, SQL/Python pipelines, predictive and prescriptive models, statistical tests, and operational dashboards. Excel, HTML/CSS/JS, Data Factory, Databricks and basic DevOps are additional tool advantages. This mapping concerns the supplied role description; no claim of employer endorsement is made.

| Stage | Work | Current status |
|---|---|---|
| Business framing | Define decision time, denominators, observational hypotheses and limits | Written |
| SQL/Python engineering | Verify 9 files; type/clean data; preserve order/item/seller grains; export Parquet | Implemented and executed |
| Exploratory analysis | 12 SQL reports with CTEs, joins, window functions and explicit denominators | Implemented and executed |
| Statistics | Four month-adjusted exploratory contrasts, purchase-week clustered uncertainty and Holm correction | Implemented, executed and independently reconciled; association only |
| Prediction | Approval-time features, six candidate setups, forward validation, calibration attempt and newer-period diagnosis | Implemented and trained locally; experimental ranker, modest reused-August gain, weak probability reliability; first independent test failure preserved |
| Prescriptive planning | Outcome-blind constrained review queue, three baselines, seven time/capacity scenarios | Implemented and executed locally; all batches optimal, 784 feasibility and 28 exhaustive real-subset checks passed; durations are assumptions, no causal savings claim |
| Excel | Five-sheet workbook with KPI formulas, SUMIFS summaries, three charts, executed-scenario selectors and separate staffing inputs | Built, native-opened, recalculated, saved and verified; formula summaries, no native PivotTables claimed |
| Power BI | Four native pages, eight imported tables, five relationships, 30 DAX measures and 52 visual elements | Built and native-saved as PBIX; nine engine queries and all four page reviews passed; portable snapshot, no live cloud refresh |
| Web interface | Approved Midnight Editorial dashboard, cohort filters, SQL comparisons, saved scenarios and a bounded one-batch optimizer | Implemented and executed locally; 37 API checks and browser flows passed; all-source snapshot, no real delivery actions or persistent user-input collection |
| Databricks | Free Edition CLI/SQL API; verified volume handoff; 9 bronze Delta tables, silver order table and gold view | Implemented, executed and independently reconciled; SQL notebook imported, no notebook job run claimed |
| Azure | Protected Free Trial; private storage and one bounded manual Data Factory copy | Implemented and executed; all 9 file hashes verified; no scheduled triggers or paid upgrade |
| DevOps/publication | Tests, reproducible instructions, GitHub and live demo | 99 local tests passed; local launchers and usage guide completed; GitHub source and Vercel frontend/Render API published |

Azure Databricks and the existing standalone Databricks Free Edition workspace are different offerings. The executed path uses Azure Data Factory followed by a hash-verified local file handoff into a Databricks volume. Native Data Factory-to-Azure-Databricks execution is not claimed. The actual SQL API execution, reconciliations, trial protection and stopped warehouse are recorded in `CLOUD_VERIFICATION.json`.

Interview practice will cover both projects together after this project is finished. Resume wording is deferred until the end, as requested.

The updated model was selected on four pre-August forward folds and refitted with
more recent mature outcomes. Because August had already been inspected in the failed
first test, current August figures are reused diagnostics. Independent new-period
validation and reliable probability calibration are not established. The portfolio
will retain those limits rather than describe a production-qualified predictor.

Statistics and review planning are recorded in `OPERATIONS_RESULTS.md` and
`OPERATIONS_VERIFICATION.json`. The default queue offers 721 orders across 28
historical daily batches under 120 pooled minutes, 30 reviews and 5 reviews per
primary seller. The 79 known late outcomes found in that queue are a retrospective
diagnostic, not delays prevented. Excel and Power BI reporting are now complete;
the approved web dashboard is also implemented locally. The frontend is live at https://delivery-ops-mk.vercel.app/ with its API on Render.
Reporting evidence and usage instructions are in `REPORTING_VERIFICATION.json` and
`REPORTING_GUIDE.md`; dashboard evidence and usage are in `DASHBOARD_VERIFICATION.json`
and `DASHBOARD_GUIDE.md`.


The current live deployment and server-connection flow are recorded in [HOSTING_GUIDE.md](HOSTING_GUIDE.md) and [SPLIT_HOSTING_VERIFICATION.json](SPLIT_HOSTING_VERIFICATION.json).
