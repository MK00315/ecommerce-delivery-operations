# Azure delivery-data demonstration: approved and executed

The Azure subscription is active and the signed-in user has the Owner role.
The billing portal shows an active free-credit offer expiring in 30 days,
no charges reported this month and INR 0.00 due. The user approved an INR 100
trial-credit working budget. The official CLI independently confirms the
FreeTrial quota and spending limit On. The remaining credit balance is unverified.
The approved private storage and Data Factory resources were created. One manual
copy succeeded on its first attempt, and all nine destination hashes matched the
original source manifest. See `../docs/CLOUD_VERIFICATION.json` for actual execution.

## Resources and execution

| Item | Proposed configuration |
| --- | --- |
| Resource group | `rg-delivery-portfolio`, Central India |
| Storage | One StorageV2 account, hierarchical namespace, Hot Standard LRS |
| Data access | Private containers; anonymous blob access disabled; HTTPS and TLS 1.2 required |
| Containers | `landing` and `bronze`; the existing 9 public Olist CSV files only |
| Data Factory | One v2 factory, Azure integration runtime in the same region |
| Pipeline | One manual Binary Copy activity from `landing/olist-v2` to `bronze/olist-v2` |
| Execution limit | At most 3 manual attempts, each with 4 DIUs, a 5-minute activity timeout and zero retries |
| Stored volume | Under 0.5 GB including both copies and manifests |
| Authorization | Data Factory managed identity limited to this new storage account; no saved storage keys |
| Validation | List all 9 destination files, download them and compare SHA-256 hashes to the original manifest |
| Retention | Keep the evidence locally; review resource retention before the trial ends |

Resource creation and actual copy execution succeeded in Central India. There are
no scheduled triggers, mapping data
flows, paid Databricks clusters, VMs, Marketplace purchases or subscription upgrades.

The Databricks account is standalone Free Edition, separate from Azure Databricks.
The Azure copy and the Databricks SQL/Delta execution have separate evidence and a
verified local file handoff. Native ADF-to-Azure-Databricks orchestration is not claimed.

## Estimated trial-credit use

The estimate uses Microsoft's current Central India INR retail meters, retrieved
on 25 October 2026. It intentionally excludes free-service allowances and assumes
all three copy attempts consume their full five minutes.

| Component | Assumption | Estimated INR |
| --- | --- | ---: |
| Copy compute | 3 runs x 5 minutes x 4 DIUs, INR 23.9974 per DIU-hour | 24.00 |
| Activity orchestration | 3 activity runs, INR 95.9894 per 1,000 | 0.29 |
| Storage | 0.5 GB for a full month, INR 1.9198 per GB-month | 0.96 |
| Storage writes | Allowance of 1,000 operations, INR 6.9112 per 10,000 | 0.69 |
| Storage reads | Allowance of 1,000 operations, INR 0.5759 per 10,000 | 0.06 |
| Factory authoring | Allowance of 1,000 entity operations, INR 47.9947 per 50,000 | 0.96 |
| Factory monitoring | Allowance of 1,000 reads, INR 23.9974 per 50,000 | 0.48 |
| **Estimated subtotal** | Before tax or any unlisted network usage | **27.43** |

Use approximately **INR 30** as the planning estimate. The user approved
at most **INR 100 of trial credit** as a working budget. This is not an Azure hard
cap: custom spending limits are unavailable and reported costs can arrive late.
Before execution, confirm the trial still covers the selected services. Stop if an
upgrade, a separate payment or an unexpected service is required. Do not authorize
paid spending from this proposal. Further runs or larger services require a new
review. No automatic resource deletion is configured by this plan.

Before downloading the data, Microsoft's bandwidth table and Central India retail
meters were checked: the first 100 GB/month of internet egress has a zero-rate tier.
This demonstration's transfer is below 1 GB. The original planning subtotal excludes
network use rather than promising an actual final bill. The copy itself remains
within the same account and region. The activity reported 0.0666667 DIU-hours, about
INR 1.60 for copy compute alone; final total usage and credit deduction are unverified.
The offer is unsupported by the attempted Cost Management API query.

## User intervention

1. The trial-credit budget has been approved; no further budget approval is needed
   for this bounded demonstration.
2. Complete any Microsoft or Databricks sign-in/consent screen personally when asked.
3. Databricks CLI access and actual project SQL execution succeeded. Its console
   explicitly rejects automated browser control; the supported CLI/SQL API was used.

Passwords, verification codes and payment details stay on the providers' pages.
The project's local SQL/model/report work can continue independently.

## Sources and evidence

- [Azure Data Factory pipeline pricing](https://azure.microsoft.com/en-us/pricing/details/data-factory/data-pipeline/)
- [Azure Blob Storage pricing](https://azure.microsoft.com/en-us/pricing/details/storage/blobs/)
- [Azure bandwidth pricing](https://azure.microsoft.com/en-us/pricing/details/bandwidth/)
- [Official Azure Retail Prices API](https://prices.azure.com/api/retail/prices)
- [Azure spending-limit behavior](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/spending-limit)
- `demo_cost_estimate.json` records the selected meter IDs and calculation.
- Private account verification: `docs/CLOUD_STATUS.json`; screenshot is kept outside
  the repository in `outputs/Delivery_Cloud_Setup/Azure_Trial_Verified.png`.
