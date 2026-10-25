# Native Power BI artifacts

- `../reports/native/Ecommerce_Delivery_Operations.pbix`: complete, loaded four-page report. Download and open in Power BI Desktop.
- `project/Delivery.pbip`: editable PBIP/PBIR/TMDL source. Its portable embedded queries can load with Desktop Refresh.
- `build_report.py`: builds the source project from `reports/reporting/` and the model evidence. Its default output is `powerbi/project`; `--layout-only` preserves the existing semantic model. Inspect it before regenerating an already native-saved artifact.
- `verify_native_model.ps1`: read-only TOM/ADOMD checks against a selected running Desktop process. The original authoring environment used official Microsoft Analysis Services client DLLs under `work/powerbi-tools/clients` outside the repository. Install those client libraries and adjust the client-root path before using this optional script on another machine.

These reports use historical snapshots. They do not sign in to Azure/Databricks, perform a live refresh, or run the optimizer. Do not commit the `.pbi` Desktop cache. The historical checks are recorded in `docs/REPORTING_VERIFICATION.json`.
