"""Budget guards must fail before submitting an additional metered operation."""

import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "azure/cloud_demo.py"
SPEC = importlib.util.spec_from_file_location("cloud_demo", SOURCE)
cloud = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cloud)


def offline_demo(attempts):
    demo = cloud.AzureDemo.__new__(cloud.AzureDemo)
    demo.state = {"upload_verified_at": "2026-10-25", "attempts": attempts}

    def forbidden(*args, **kwargs):
        pytest.fail("A blocked action must not make an Azure request.")

    demo.request = forbidden
    return demo


def test_fourth_copy_attempt_is_blocked_without_contacting_azure():
    demo = offline_demo([{"status": "Failed"} for _ in range(3)])
    with pytest.raises(RuntimeError, match="maximum of three"):
        demo.run()


@pytest.mark.parametrize("status", ["Submitting", "CancelRequested"])
def test_unknown_submission_cannot_create_a_duplicate_run(status):
    demo = offline_demo([{"status": status}])
    with pytest.raises(RuntimeError, match="unresolved"):
        demo.run()


def test_successful_copy_is_not_repeated():
    demo = offline_demo([{"status": "Succeeded", "run_id": "existing-run"}])
    demo.run()


@pytest.mark.parametrize("policies", [
    {"quotaId": "FreeTrial_2014-09-01", "spendingLimit": "Off"},
    {"quotaId": "PayAsYouGo_2014-09-01", "spendingLimit": "On"},
])
def test_trial_protection_cannot_be_replaced_by_a_paid_or_unprotected_plan(policies):
    demo = cloud.AzureDemo.__new__(cloud.AzureDemo)
    demo.base = "/subscriptions/offline-test"
    demo.state = {}
    demo.request = lambda *args, **kwargs: {"state": "Enabled", "subscriptionPolicies": policies}
    with pytest.raises(RuntimeError):
        demo.guard_trial()
    assert "trial_policy_verified_at" not in demo.state
