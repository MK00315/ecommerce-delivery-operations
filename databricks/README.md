# Databricks cloud ingestion and reconciliation

The public Olist files were copied by Azure Data Factory into Azure bronze storage,
downloaded and verified locally, then uploaded to a Unity Catalog managed volume
in Databricks Free Edition. All nine uploaded files were downloaded again and their
SHA-256 hashes matched the original manifest.

This is a documented file handoff. The Free Edition workspace is separate from
Azure Databricks; no native ADF notebook activity connection is claimed.

## Executed result

- 9 bronze Delta tables containing 1,550,922 original source rows.
- One silver table retaining all 99,441 orders, plus one gold delivery overview view.
- 96,470 eligible deliveries, 6,534 late orders and 89,936 on-time orders.
- Exact order, eligibility, late and on-time ID memberships match the local DuckDB
  pipeline, verified by deterministic SHA-256 hashes in separate engines.
- Item, freight and payment totals match independent Decimal sums over original CSVs.
- The serverless starter warehouse was stopped after verification.

The SQL definitions were executed through the supported SQL Statement Execution API.
A reproducible SQL notebook was imported into `/Shared/Delivery_Operations/01_Bronze_And_SLA`.
No native notebook job run, Python model training or paid Databricks deployment is claimed.

## Reproduce

Use the project environment, the original data manifest, a supported official CLI
OAuth profile and the previously verified Azure handoff files. Authenticate directly
with the official Databricks CLI; do not paste or save access tokens in the project.

From the project root, with `databricks` available in the current shell:

```powershell
python databricks/run_cloud_ingestion.py render
python databricks/run_cloud_ingestion.py execute --profile delivery-project
python databricks/verify_cloud_labels.py --profile delivery-project
```

The first command only renders `01_bronze_and_sla.sql`. The second creates the
project schema and volume, verifies file transfers, creates Delta tables and
reconciles counts and money totals. The third checks exact label membership.

The pipeline uses explicit string schemas to preserve source IDs and postcode
zeros. Multiline CSV reviews and doubled quotes are handled explicitly. Invalid or
unusable delivery outcomes retain unknown labels, and delivery on the promised
calendar date counts as on time. Actual delivery and review outcomes belong to
reporting; they are not prediction features available at approval time.

Existing different files are not overwritten. Managed tables use `IF NOT EXISTS`,
so this demonstration does not replace pre-existing tables. Reruns validate their
results and fail on a mismatch. The imported notebook is also not overwritten.
Raw source files, verified downloads and private account-scoped evidence are ignored
by Git. Keep execution records in `reports/databricks/` and publish only the sanitized
summary in `docs/CLOUD_VERIFICATION.json`.

The warehouse retains its ten-minute auto-stop setting. After manual work, stop the
starter warehouse through its normal controls to conserve the Free Edition quota.

## Official references

- [CLI OAuth user authentication](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m)
- [Read files with explicit schemas](https://docs.databricks.com/aws/en/sql/language-manual/functions/read_files)
- [SQL Statement Execution API](https://docs.databricks.com/api/workspace/statementexecution)
