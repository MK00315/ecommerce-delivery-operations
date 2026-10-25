"""Provision and verify a bounded Azure Data Factory file-copy demonstration.

Requires the approved local budget record, an authenticated official Azure CLI,
and the project's original Olist manifest. Tokens and storage keys are never saved
by this script. Execution evidence belongs in ignored reports/azure/.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.identity import AzureCliCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "reports/azure"
STATE_FILE = EVIDENCE / "cloud_state.json"
MANIFEST_FILE = ROOT / "docs/raw_dataset_manifest.json"
RG = "rg-delivery-portfolio"
REGION = "centralindia"
PIPELINE = "Copy_Olist_Landing_To_Bronze"
PROJECT_TAG = "ecommerce-delivery-operations"
STORAGE_API = "2023-05-01"
ADF_API = "2018-06-01"
CONTRIBUTOR = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
READER = "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".writing")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def log(message):
    print(message, flush=True)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_approval():
    approval = read(ROOT / "azure/demo_cost_estimate.json")
    if not approval.get("budget_approved") or approval.get("working_budget_inr") != "100":
        raise RuntimeError("The INR 100 trial-credit budget must be approved first.")
    if approval.get("paid_spending_authorized") or approval.get("subscription_upgrade_authorized"):
        raise RuntimeError("This demonstration only permits the protected trial-credit setup.")


def check_sources():
    files = read(MANIFEST_FILE)["files"]
    if len(files) != 9 or sum(f["bytes"] for f in files) * 2 >= 500_000_000:
        raise RuntimeError("Source inventory is outside the approved 9-file, 0.5 GB scope.")
    for item in files:
        path = ROOT / "data/raw/olist-v2" / item["file"]
        if path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"Original source changed: {item['file']}")
    return files


def pipeline_definition():
    return {"properties": {
        "description": "Manual, bounded, byte-preserving copy of the nine original public Olist CSV files.",
        "concurrency": 1,
        "activities": [{
            "name": "Copy_Nine_Original_CSVs", "type": "Copy", "dependsOn": [],
            "policy": {"timeout": "0.00:05:00", "retry": 0, "retryIntervalInSeconds": 30,
                       "secureOutput": False, "secureInput": False},
            "typeProperties": {
                "source": {"type": "BinarySource", "storeSettings": {
                    "type": "AzureBlobFSReadSettings", "recursive": True,
                    "wildcardFileName": "*.csv"}},
                "sink": {"type": "BinarySink", "storeSettings": {
                    "type": "AzureBlobFSWriteSettings", "copyBehavior": "PreserveHierarchy"}},
                "dataIntegrationUnits": 4, "parallelCopies": 1, "enableStaging": False,
                "validateDataConsistency": True,
            },
            "inputs": [{"referenceName": "Olist_Landing_Binary", "type": "DatasetReference"}],
            "outputs": [{"referenceName": "Olist_Bronze_Binary", "type": "DatasetReference"}],
        }],
        "annotations": ["public-olist-v2", "manual-only", "trial-credit-budget-INR100"],
    }}


class AzureDemo:
    def __init__(self, subscription):
        check_approval()
        executable = shutil.which("az") or shutil.which("az.cmd")
        if not executable:
            raise RuntimeError("Add the installed official Azure CLI to this shell's PATH first.")
        command = [executable, "account", "show", "--only-show-errors", "-o", "json"]
        account = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
        if account["id"] != subscription:
            raise RuntimeError("The signed-in default subscription differs from the requested subscription.")
        self.subscription = subscription
        self.credential = AzureCliCredential(tenant_id=account["tenantId"], process_timeout=30)
        self.session = requests.Session()
        self.base = f"/subscriptions/{subscription}"
        self.rg_path = f"{self.base}/resourceGroups/{RG}"
        suffix = hashlib.sha256(subscription.encode()).hexdigest()[:10]
        self.storage_name = "stdelivery" + suffix
        self.factory_name = "adf-delivery-" + suffix
        self.storage_path = f"{self.rg_path}/providers/Microsoft.Storage/storageAccounts/{self.storage_name}"
        self.factory_path = f"{self.rg_path}/providers/Microsoft.DataFactory/factories/{self.factory_name}"
        self.state = read(STATE_FILE) if STATE_FILE.exists() else {
            "created_at": now(), "subscription_id": subscription, "resource_group": RG,
            "region": REGION, "storage_account": self.storage_name, "factory": self.factory_name,
            "pipeline": PIPELINE, "attempts": [], "budget_inr": 100,
            "paid_upgrade_authorized": False,
        }
        if self.state["subscription_id"] != subscription:
            raise RuntimeError("Existing execution evidence belongs to another subscription.")
        self.guard_trial()

    def request(self, method, path, api_version, body=None, allow_404=False, query_params=None):
        token = self.credential.get_token("https://management.azure.com/.default").token
        response = self.session.request(
            method, "https://management.azure.com" + path,
            params={"api-version": api_version, **(query_params or {})}, json=body,
            headers={"Authorization": "Bearer " + token}, timeout=90,
        )
        if response.status_code == 404 and allow_404:
            return None
        if not response.ok:
            try:
                detail = response.json().get("error", {})
                message = f"{detail.get('code', response.status_code)}: {detail.get('message', '')}"
            except ValueError:
                message = str(response.status_code)
            raise RuntimeError(f"Azure {method} failed: {message}")
        return response.json() if response.content else {}

    def persist(self):
        self.state["updated_at"] = now()
        save(STATE_FILE, self.state)

    def guard_trial(self):
        subscription = self.request("GET", self.base, "2022-12-01")
        policies = subscription.get("subscriptionPolicies", {})
        if subscription["state"] != "Enabled" or not policies.get("quotaId", "").startswith("FreeTrial"):
            raise RuntimeError("An enabled Free Trial subscription is required. No paid upgrade is permitted.")
        if policies.get("spendingLimit") != "On":
            raise RuntimeError("The trial spending limit must remain On; this script will not change it.")
        self.state["trial_policy_verified_at"] = now()
        self.state["subscription_policies"] = policies
        self.persist()

    def inspect(self):
        files = check_sources()
        providers = {}
        for namespace, resource_type in [("Microsoft.Storage", "storageAccounts"), ("Microsoft.DataFactory", "factories")]:
            value = self.request("GET", f"{self.base}/providers/{namespace}", "2021-04-01")
            resource = next(t for t in value["resourceTypes"] if t["resourceType"] == resource_type)
            if "Central India" not in resource["locations"]:
                raise RuntimeError(f"Central India is not listed for {namespace}.")
            providers[namespace] = value["registrationState"]
        self.state["preflight"] = {
            "checked_at": now(), "provider_registration": providers,
            "original_files_verified": len(files), "original_bytes": sum(f["bytes"] for f in files),
            "regional_provider_support": True,
            "subscription_deployment_policy": "Actual creation may still be denied by subscription-specific policy",
        }
        self.persist()
        log(json.dumps(self.state["preflight"], indent=2))

    def register_provider(self, namespace):
        path = f"{self.base}/providers/{namespace}"
        result = self.request("GET", path, "2021-04-01")
        if result["registrationState"] == "Registered":
            return
        self.request("POST", path + "/register", "2021-04-01", {})
        start = time.monotonic()
        while time.monotonic() - start < 600:
            result = self.request("GET", path, "2021-04-01")
            if result["registrationState"] == "Registered":
                log(f"Registered {namespace}.")
                return
            log(f"Waiting for {namespace} registration...")
            time.sleep(10)
        raise RuntimeError(f"Provider registration still pending: {namespace}. No metered copy has run.")

    def assign_role(self, scope, principal, role, principal_type):
        assignment = str(uuid.uuid5(uuid.NAMESPACE_URL, scope.lower() + principal + role))
        return self.request("PUT", scope + "/providers/Microsoft.Authorization/roleAssignments/" + assignment,
                            "2022-04-01", {"properties": {
                                "roleDefinitionId": self.base + "/providers/Microsoft.Authorization/roleDefinitions/" + role,
                                "principalId": principal, "principalType": principal_type,
                            }})

    def provision(self):
        self.inspect()
        for namespace in ["Microsoft.Storage", "Microsoft.DataFactory"]:
            self.register_provider(namespace)
        group = self.request("GET", self.rg_path, "2022-09-01", allow_404=True)
        if group and group.get("tags", {}).get("Project") != PROJECT_TAG:
            raise RuntimeError("The existing resource group is outside this project's ownership tags.")
        tags = {"Project": PROJECT_TAG, "Environment": "portfolio", "TrialCreditBudgetINR": "100",
                "RetentionReviewDate": (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()}
        self.request("PUT", self.rg_path, "2022-09-01", {"location": REGION, "tags": tags})
        storage = self.request("GET", self.storage_path, STORAGE_API, allow_404=True)
        if storage and storage.get("tags", {}).get("Project") != PROJECT_TAG:
            raise RuntimeError("The existing storage account is not owned by this demonstration.")
        if not storage:
            availability = self.request("POST", self.base + "/providers/Microsoft.Storage/checkNameAvailability",
                                        STORAGE_API, {"name": self.storage_name, "type": "Microsoft.Storage/storageAccounts"})
            if not availability.get("nameAvailable"):
                raise RuntimeError("The proposed storage account name is unavailable; no alternative is created automatically.")
            self.request("PUT", self.storage_path, STORAGE_API, {
                "location": REGION, "kind": "StorageV2", "sku": {"name": "Standard_LRS"}, "tags": tags,
                "properties": {"isHnsEnabled": True, "accessTier": "Hot", "minimumTlsVersion": "TLS1_2",
                               "supportsHttpsTrafficOnly": True, "allowBlobPublicAccess": False,
                               "allowSharedKeyAccess": False, "publicNetworkAccess": "Enabled"},
            })
        start = time.monotonic()
        while time.monotonic() - start < 600:
            storage = self.request("GET", self.storage_path, STORAGE_API)
            status = storage["properties"]["provisioningState"]
            if status == "Succeeded":
                break
            if status in {"Failed", "Canceled"}:
                raise RuntimeError("Storage provisioning " + status)
            log("Waiting for storage provisioning...")
            time.sleep(10)
        else:
            raise RuntimeError("Storage provisioning is still pending.")
        for container in ["landing", "bronze"]:
            self.request("PUT", self.storage_path + "/blobServices/default/containers/" + container,
                         STORAGE_API, {"properties": {"publicAccess": "None"}})
        log("Private storage containers provisioned; shared-key authentication disabled.")
        existing_factory = self.request("GET", self.factory_path, ADF_API, allow_404=True)
        if existing_factory and existing_factory.get("tags", {}).get("Project") != PROJECT_TAG:
            raise RuntimeError("Existing factory has different ownership tags.")
        factory = self.request("PUT", self.factory_path, ADF_API, {
            "location": REGION, "identity": {"type": "SystemAssigned"}, "tags": tags,
            "properties": {"publicNetworkAccess": "Enabled"},
        })
        principal = factory["identity"]["principalId"]
        token = self.credential.get_token("https://management.azure.com/.default").token
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        user_principal = claims["oid"]
        self.assign_role(self.storage_path, user_principal, CONTRIBUTOR, "User")
        self.assign_role(self.storage_path + "/blobServices/default/containers/landing", principal, READER, "ServicePrincipal")
        self.assign_role(self.storage_path + "/blobServices/default/containers/bronze", principal, CONTRIBUTOR, "ServicePrincipal")
        self.request("PUT", self.factory_path + "/integrationruntimes/AzureCentralIndia", ADF_API, {
            "properties": {"type": "Managed", "typeProperties": {"computeProperties": {"location": REGION}}},
        })
        self.request("PUT", self.factory_path + "/linkedservices/Olist_Private_Lake", ADF_API, {"properties": {
            "type": "AzureBlobFS", "typeProperties": {"url": f"https://{self.storage_name}.dfs.core.windows.net"},
            "connectVia": {"referenceName": "AzureCentralIndia", "type": "IntegrationRuntimeReference"},
        }})
        for name, container in [("Olist_Landing_Binary", "landing"), ("Olist_Bronze_Binary", "bronze")]:
            self.request("PUT", self.factory_path + "/datasets/" + name, ADF_API, {"properties": {
                "linkedServiceName": {"referenceName": "Olist_Private_Lake", "type": "LinkedServiceReference"},
                "type": "Binary", "typeProperties": {"location": {
                    "type": "AzureBlobFSLocation", "fileSystem": container, "folderPath": "olist-v2"}},
            }})
        self.request("PUT", self.factory_path + "/pipelines/" + PIPELINE, ADF_API, pipeline_definition())
        triggers = self.request("GET", self.factory_path + "/triggers", ADF_API)["value"]
        if triggers:
            raise RuntimeError("Unexpected factory triggers exist. The manual demo will not run.")
        self.state["provisioned_at"] = now()
        self.state["storage_configuration"] = {
            k: storage["properties"].get(k) for k in ["isHnsEnabled", "minimumTlsVersion", "allowBlobPublicAccess", "allowSharedKeyAccess", "supportsHttpsTrafficOnly"]
        }
        self.state["managed_identity_roles"] = {"landing": "Storage Blob Data Reader", "bronze": "Storage Blob Data Contributor"}
        self.state["scheduled_triggers"] = 0
        self.persist()
        save(EVIDENCE / "deployed_pipeline.json", self.request("GET", self.factory_path + "/pipelines/" + PIPELINE, ADF_API))
        log("Data Factory provisioned with scoped managed identity and one manual copy pipeline. No copy run submitted.")

    def blob_client(self):
        return BlobServiceClient(f"https://{self.storage_name}.blob.core.windows.net", credential=self.credential)

    def wait_for_blob_access(self, client):
        start = time.monotonic()
        while time.monotonic() - start < 600:
            try:
                list(client.get_container_client("landing").list_blobs(results_per_page=1))
                return
            except HttpResponseError as error:
                if error.status_code != 403:
                    raise
                log("Waiting for the new storage role to become effective...")
                time.sleep(15)
        raise RuntimeError("Storage access is still propagating; rerun upload later. No copy run submitted.")

    def upload(self):
        if not self.state.get("provisioned_at"):
            raise RuntimeError("Provision the bounded resources first.")
        files = check_sources()
        client = self.blob_client()
        self.wait_for_blob_access(client)
        for item in files:
            blob = client.get_blob_client("landing", "olist-v2/" + item["file"])
            try:
                props = blob.get_blob_properties()
            except ResourceNotFoundError:
                with (ROOT / "data/raw/olist-v2" / item["file"]).open("rb") as stream:
                    blob.upload_blob(stream, overwrite=False, metadata={"sha256": item["sha256"]},
                                     content_settings=ContentSettings(content_type="text/csv"))
            else:
                digest = hashlib.sha256()
                for chunk in blob.download_blob().chunks():
                    digest.update(chunk)
                if props.size != item["bytes"] or digest.hexdigest() != item["sha256"]:
                    raise RuntimeError("A different blob already exists; it will not be overwritten.")
            log("Uploaded or independently verified " + item["file"])
        self.state["upload_verified_at"] = now()
        self.state["uploaded_files"] = len(files)
        self.state["uploaded_bytes"] = sum(f["bytes"] for f in files)
        self.persist()

    def run(self):
        if not self.state.get("upload_verified_at"):
            raise RuntimeError("Upload and verify the original sources first.")
        attempts = self.state["attempts"]
        if attempts and attempts[-1].get("status") == "Succeeded":
            log("A successful run already exists; no duplicate metered run submitted.")
            return
        if attempts and attempts[-1].get("status") in {"Submitting", "InProgress", "Queued", "CancelRequested"}:
            run_id = attempts[-1].get("run_id")
            if not run_id:
                raise RuntimeError("A previous submission is unresolved. Reconcile the run history before another attempt.")
            log("Resuming monitoring of the existing run; no new run submitted.")
        else:
            if len(attempts) >= 3:
                raise RuntimeError("The approved maximum of three manual attempts is reached.")
            deployed = self.request("GET", self.factory_path + "/pipelines/" + PIPELINE, ADF_API)
            expected = pipeline_definition()["properties"]
            actual = deployed["properties"]
            if actual["activities"] != expected["activities"] or actual.get("concurrency") != 1:
                raise RuntimeError("The deployed pipeline differs from the bounded, reviewed definition.")
            if self.request("GET", self.factory_path + "/triggers", ADF_API)["value"]:
                raise RuntimeError("Unexpected scheduled trigger; no manual run submitted.")
            attempts.append({"submitted_at": now(), "status": "Submitting"})
            self.persist()
            result = self.request("POST", self.factory_path + "/pipelines/" + PIPELINE + "/createRun", ADF_API, {})
            run_id = result["runId"]
            attempts[-1].update({"run_id": run_id, "status": "Queued"})
            self.persist()
            log("Submitted manual copy attempt " + str(len(attempts)) + ": " + run_id)
        started = time.monotonic()
        while time.monotonic() - started < 600:
            result = self.request("GET", self.factory_path + "/pipelineruns/" + run_id, ADF_API)
            attempts[-1]["status"] = result["status"]
            self.persist()
            if result["status"] in {"Succeeded", "Failed", "Cancelled"}:
                save(EVIDENCE / ("pipeline_run_" + run_id + ".json"), result)
                query = {"lastUpdatedAfter": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                         "lastUpdatedBefore": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
                activity = self.request("POST", self.factory_path + "/pipelineruns/" + run_id + "/queryActivityruns", ADF_API, query)
                save(EVIDENCE / ("activity_runs_" + run_id + ".json"), activity)
                log("Copy pipeline finished: " + result["status"])
                if result["status"] != "Succeeded":
                    raise RuntimeError("Copy did not succeed. Inspect recorded activity evidence before a manual retry.")
                return
            log("Copy status: " + result["status"])
            time.sleep(10)
        self.request("POST", self.factory_path + "/pipelineruns/" + run_id + "/cancel", ADF_API,
                     query_params={"isRecursive": "true"})
        attempts[-1]["status"] = "CancelRequested"
        self.persist()
        raise RuntimeError("Monitoring deadline reached; cancellation requested and further execution stopped.")

    def verify(self):
        if not self.state["attempts"] or self.state["attempts"][-1].get("status") != "Succeeded":
            raise RuntimeError("A successful copy run is required before destination verification.")
        files = check_sources()
        expected = {"olist-v2/" + f["file"]: f for f in files}
        client = self.blob_client()
        output = list(client.get_container_client("bronze").list_blobs(
            name_starts_with="olist-v2/", include=["metadata"]))
        actual = {b.name: b for b in output if (b.metadata or {}).get("hdi_isfolder") != "true"}
        if set(actual) != set(expected):
            raise RuntimeError("Destination file inventory differs from the original nine CSV files.")
        comparisons = []
        handoff_directory = ROOT / "data/interim/azure-bronze/olist-v2"
        handoff_directory.mkdir(parents=True, exist_ok=True)
        for name, item in expected.items():
            digest = hashlib.sha256()
            size = 0
            handoff_file = handoff_directory / item["file"]
            temporary = handoff_file.with_suffix(handoff_file.suffix + ".downloading")
            with temporary.open("wb") as stream:
                for block in client.get_blob_client("bronze", name).download_blob().chunks():
                    digest.update(block)
                    size += len(block)
                    stream.write(block)
            if digest.hexdigest() != item["sha256"] or size != item["bytes"]:
                raise RuntimeError("Byte-for-byte destination verification failed for " + name)
            os.replace(temporary, handoff_file)
            comparisons.append({"file": item["file"], "bytes": size, "sha256": digest.hexdigest(), "matches_original": True})
            log("Destination SHA-256 matched: " + item["file"])
        proof = {"verified_at": now(), "pipeline_run_id": self.state["attempts"][-1]["run_id"],
                 "files_verified": len(comparisons), "bytes_verified": sum(f["bytes"] for f in comparisons),
                 "all_original_hashes_match": True, "files": comparisons,
                 "verified_local_handoff_directory": "data/interim/azure-bronze/olist-v2",
                 "data_scope": "Original public Olist version 2 CSV files; cloud copy only, no model training"}
        save(EVIDENCE / "destination_verification.json", proof)
        self.state["destination_verified_at"] = proof["verified_at"]
        self.persist()
        log("All nine destination files match their original bytes and hashes.")

    def cost(self):
        query = {"type": "ActualCost", "timeframe": "MonthToDate", "dataset": {
            "granularity": "None", "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
            "filter": {"dimensions": {"name": "ResourceGroupName", "operator": "In", "values": [RG]}}}}
        try:
            result = self.request("POST", self.base + "/providers/Microsoft.CostManagement/query", "2023-11-01", query)
            save(EVIDENCE / "reported_cost.json", {"queried_at": now(), "data": result,
                 "limitation": "Azure cost reporting may lag. Empty or zero rows do not prove zero actual consumption."})
            log("Saved Azure's currently reported cost; delayed usage may not yet be included.")
        except RuntimeError as error:
            save(EVIDENCE / "reported_cost.json", {"queried_at": now(), "available": False, "reason": str(error),
                 "limitation": "No final bill or actual credit deduction is claimed."})
            log("Current cost data is unavailable; the reason was recorded without changing the subscription.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["inspect", "provision", "upload", "run", "verify", "cost"])
    parser.add_argument("--subscription", required=True)
    args = parser.parse_args()
    demo = AzureDemo(args.subscription)
    getattr(demo, args.stage)()


if __name__ == "__main__":
    main()
