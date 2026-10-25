# Azure ingestion demonstration

This stage copies the original Olist CSV files into an authenticated Azure lake
and uses one manual Data Factory activity to move them from landing to bronze.
It demonstrates cloud ingestion, managed-identity access, execution monitoring and
independent source-to-destination integrity checks. It does not train the delivery
model or replace the project's SQL cleaning stage.

The concrete resource and cost scope is in [CLOUD_DEMO_PLAN.md](CLOUD_DEMO_PLAN.md).
Azure's Free Trial policy and spending limit must be verified before every command.
The existing Databricks Free Edition workspace is a separate service; this stage
does not claim native ADF-to-Azure-Databricks integration.

## Reproduce with your own subscription

Use the project's Python environment and the official Azure CLI. Authenticate
interactively with `az login`; keep credentials outside the repository. The
default CLI subscription must be the subscription supplied to the script.
The local approval record must explicitly approve this bounded trial-credit run.

From the project root, run these stages in order, substituting your subscription
ID locally. Do not put access tokens or storage keys into these commands.

```powershell
$deliverySubscription = '<your-subscription-id>'
python azure/cloud_demo.py inspect --subscription $deliverySubscription
python azure/cloud_demo.py provision --subscription $deliverySubscription
python azure/cloud_demo.py upload --subscription $deliverySubscription
python azure/cloud_demo.py run --subscription $deliverySubscription
python azure/cloud_demo.py verify --subscription $deliverySubscription
python azure/cloud_demo.py cost --subscription $deliverySubscription
```

`inspect` is read-only against Azure. `provision` registers the two required
providers, creates a tagged resource group, one storage account, two containers,
one factory and its manual pipeline. User uploads use the current Azure identity;
the factory reads landing and writes bronze through its own scoped managed identity.
Anonymous blob access and shared-key authentication are disabled.

`upload` refuses to overwrite differing existing files. `run` records the attempt
before submission, allows at most three attempts and resumes monitoring a known
pending run. It does not submit another run after success. An unresolved submission
must be reconciled against Azure's run history before any retry. Each activity has
zero retries, four DIUs and a five-minute timeout; there are no scheduled triggers.

`verify` streams every destination file from Azure, recomputes its SHA-256 hash and
checks the exact nine-file inventory and byte totals against the original source
manifest. Matching metadata alone is not accepted as a content-integrity check.

## Evidence and retention

Execution records are written to ignored `reports/azure/`:

- `cloud_state.json`: account-scoped resource inventory and attempt ledger.
- `deployed_pipeline.json`: the actual definition read back from Azure.
- `pipeline_run_*.json` and `activity_runs_*.json`: service execution evidence.
- `destination_verification.json`: independently downloaded destination hashes.
- `reported_cost.json`: currently reported usage, or the reason it is unavailable.

Cost data can arrive late; an empty cost result is not evidence of zero use.
The INR 100 working budget is not an automatic hard cap. Trial protection stays on,
and the script refuses a paid subscription or upgrade. The resource group is tagged
with a retention review date. Deletion is a separate user decision; none is scheduled.

Keep private account IDs and sign-in evidence outside a public portfolio. Publish
only a reviewed, sanitized execution summary. The raw Olist files and downloaded
project outputs are excluded from Git.

## Official implementation references

- [ADLS Gen2 and managed-identity authentication](https://learn.microsoft.com/en-us/azure/data-factory/connector-azure-data-lake-storage)
- [Data Factory Binary format](https://learn.microsoft.com/en-us/azure/data-factory/format-binary)
- [Pipeline run REST API](https://learn.microsoft.com/en-us/rest/api/datafactory/pipeline-runs/get)
- [Azure spending limits](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/spending-limit)
