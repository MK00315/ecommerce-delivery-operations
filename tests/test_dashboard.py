"""Independent cohort and API-boundary checks for the actual reporting snapshot."""
import csv
from collections import Counter
from datetime import date
import hashlib
import io
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import delivery_dashboard as dashboard


@pytest.fixture(scope="module")
def client():
    with TestClient(dashboard.app) as session:
        yield session


@pytest.fixture(scope="module")
def original():
    # Independent source CSV, rather than the compact serving database.
    raw = pd.read_csv(dashboard.ROOT / "data/raw/olist-v2/olist_orders_dataset.csv")
    raw["purchase_date"] = pd.to_datetime(raw.order_purchase_timestamp).dt.date
    raw["eligible"] = raw.order_status.eq("delivered") & raw.order_delivered_customer_date.notna() & raw.order_estimated_delivery_date.notna()
    raw["late"] = raw.eligible & (pd.to_datetime(raw.order_delivered_customer_date).dt.normalize() > pd.to_datetime(raw.order_estimated_delivery_date).dt.normalize())
    customers = pd.read_csv(dashboard.ROOT / "data/raw/olist-v2/olist_customers_dataset.csv")
    return raw.merge(customers[["customer_id", "customer_state"]], on="customer_id", validate="many_to_one")


@pytest.mark.parametrize("state,start,end", [("ALL", "2016-09-04", "2018-10-17"),
    ("SP", "2016-09-04", "2018-10-17"), ("RJ", "2018-03-01", "2018-03-31"),
    ("ALL", "2018-03-01", "2018-03-31"), ("AC", "2017-11-01", "2018-02-28")])
def test_filters_reconcile_to_original_csvs(client, original, state, start, end):
    selected = original.loc[original.purchase_date.between(date.fromisoformat(start), date.fromisoformat(end))]
    if state != "ALL":
        selected = selected.loc[selected.customer_state.eq(state)]
    response = client.get("/api/view", params={"state": state, "start": start, "end": end})
    assert response.status_code == 200
    body = response.json()
    metric = body["metrics"]
    assert metric["orders"] == len(selected)
    assert metric["eligible"] == int(selected.eligible.sum())
    assert metric["late"] == int(selected.late.sum())
    assert metric["outside_cohort"] == len(selected) - int(selected.eligible.sum())
    assert metric["late_rate"] == pytest.approx(selected.late.sum() / selected.eligible.sum())
    assert sum(r["orders"] for r in body["monthly"]) == len(selected)
    assert sum(r["eligible"] for r in body["states"]) == int(selected.eligible.sum())
    for group in ["distance", "basket"]:
        assert sum(r["orders"] for r in body[group]) == len(selected)
        assert sum(r["eligible"] for r in body[group]) == int(selected.eligible.sum())


def test_empty_cohort_keeps_rates_and_durations_unknown(client):
    body = client.get("/api/view?start=2016-11-01&end=2016-11-30").json()
    assert body["metrics"]["orders"] == 0
    for field in ["late_rate", "mean_days", "median_days", "distance_coverage"]:
        assert body["metrics"][field] is None
    assert body["monthly"][0]["late_rate"] is None
    assert body["monthly"][0]["orders"] == 0


def test_unknown_only_cohort_is_not_reported_as_on_time(client):
    body = client.get("/api/view?start=2018-09-01&end=2018-10-17").json()
    metric = body["metrics"]
    assert metric["orders"] == metric["outside_cohort"] == 20
    assert metric["eligible"] == metric["on_time"] == metric["late"] == 0
    assert metric["late_rate"] is None and metric["mean_days"] is None
    assert all(row["late_rate"] is None for row in body["monthly"])


@pytest.mark.parametrize("query", ["state=ZZ", "state=SP%27%20OR%201%3D1--", "start=2018-04-01&end=2018-03-01",
    "start=2015-01-01", "end=2026-01-01", "start=not-a-date"])
def test_invalid_view_parameters_are_rejected(client, query):
    assert client.get("/api/view?" + query).status_code == 422


@pytest.mark.parametrize("scenario,reviews,minutes,unknown,late", [
    ("capacity_120_cost_1", 721, 3314, 24, 79), ("capacity_60_cost_1", 378, 1676, 18, 46),
    ("capacity_0_cost_1", 0, 0, 0, 0)])
def test_saved_scenarios_reconcile_and_unknowns_are_retained(client, scenario, reviews, minutes, unknown, late):
    body = client.get("/api/planning", params={"scenario": scenario}).json()
    optimized = body["policies"][0]
    assert len(body["policies"]) == 4 and len(body["daily"]) == 28
    assert [optimized[k] for k in ["selected_orders", "used_minutes", "selected_unknown_outcomes", "selected_known_late"]] == [reviews, minutes, unknown, late]
    assert optimized["candidate_known_late"] == 406
    assert optimized["candidate_unknown_outcomes"] == 103
    assert sum(r["selected_orders"] for r in body["daily"]) == reviews


def test_planning_and_evidence_do_not_change_with_overview_filter(client):
    plan = client.get("/api/planning").json()
    evidence = client.get("/api/evidence").json()
    client.get("/api/view?state=SP&start=2018-03-01&end=2018-03-31")
    assert client.get("/api/planning").json() == plan
    assert client.get("/api/evidence").json() == evidence


def test_custom_api_passes_only_decision_columns_and_verifies_actual_limits(client, monkeypatch):
    dashboard.custom_plan.cache_clear()
    real = dashboard.optimize_reviews
    seen = []

    def observe(candidates, limits):
        seen.append(candidates.copy())
        assert list(candidates.columns) == dashboard.DECISION_COLUMNS
        return real(candidates, limits)

    monkeypatch.setattr(dashboard, "optimize_reviews", observe)
    before = hashlib.sha256(dashboard.DATABASE.read_bytes()).hexdigest()
    response = client.post("/api/planning/custom", json={"batch": "2018-08-02", "minutes": 40, "maximum_reviews": 9, "per_primary_seller": 1})
    assert response.status_code == 200
    body = response.json()
    assert seen and len(body["policies"]) == 4
    assert body["saved"] is False and body["model_retrained"] is False
    for row in body["policies"]:
        assert row["selected_orders"] <= 9 and row["used_minutes"] <= 40
    assert body["policies"][0]["priority_points"] >= max(r["priority_points"] for r in body["policies"][1:]) - 1e-6
    assert max(Counter(r["primary_seller_id"] for r in body["queue"]).values(), default=0) <= 1
    assert sum(r["review_minutes"] for r in body["queue"]) <= 40
    assert all(r["approved_at"] < "2018-08-02T09:00:00" for r in body["queue"])
    assert hashlib.sha256(dashboard.DATABASE.read_bytes()).hexdigest() == before


def test_custom_zero_capacity_and_single_batch_scope(client):
    body = client.post("/api/planning/custom", json={"batch": "2018-08-02", "minutes": 0}).json()
    assert body["queue"] == []
    assert all(r["selected_orders"] == 0 for r in body["policies"])
    assert body["policies"][0]["candidate_orders"] == 325
    assert body["solver"]["optimal"] is True


def test_feasible_time_limited_result_is_not_relabelled_optimal(client, monkeypatch):
    dashboard.custom_plan.cache_clear()
    real = dashboard.optimize_reviews

    def time_limited(candidates, limits):
        ids, info = real(candidates, limits)
        return ids, {**info, "optimal": False, "status": "Time limit reached", "solver_gap": 0.25}

    monkeypatch.setattr(dashboard, "optimize_reviews", time_limited)
    result = client.post("/api/planning/custom", json={"batch": "2018-08-03", "minutes": 50}).json()
    assert result["solver"]["optimal"] is False
    assert result["solver"]["gap"] == .25
    dashboard.custom_plan.cache_clear()


@pytest.mark.parametrize("payload", [{"minutes": -1}, {"minutes": 481}, {"maximum_reviews": 61},
    {"per_primary_seller": 11}, {"minutes": 12.5}, {"minutes": True}, {"observed_label_by_cutoff": 1},
    {"batch": "2018-09-02"}])
def test_custom_plan_invalid_or_outcome_inputs_are_rejected(client, payload):
    assert client.post("/api/planning/custom", json={"batch": "2018-08-02", **payload}).status_code == 422


def test_custom_solver_busy_rejects_duplicate_parallel_work(client):
    dashboard.SOLVER_SLOT.acquire()
    try:
        assert client.post("/api/planning/custom", json={"batch": "2018-08-02"}).status_code == 429
    finally:
        dashboard.SOLVER_SLOT.release()


def test_export_uses_the_actual_applied_scope(client):
    response = client.get("/api/export?state=SP&start=2018-03-01&end=2018-03-31")
    assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))))
    expected = client.get("/api/view?state=SP&start=2018-03-01&end=2018-03-31").json()["metrics"]
    assert len(rows) == 1 and rows[0]["Customer state filter"] == "SP"
    assert int(rows[0]["Source orders"]) == expected["orders"]
    assert int(rows[0]["Late deliveries"]) == expected["late"]


@pytest.mark.parametrize("path", ["/assets/../../delivery_dashboard.py", "/data/dashboard/delivery_dashboard.duckdb",
    "/.env", "/api/downloads/credentials", "/api/planning?scenario=made-up", "/api/planning?batch=2019-01-01"])
def test_only_named_public_resources_and_scenarios_are_served(client, path):
    assert client.get(path).status_code in {404, 422}


def test_html_assets_and_report_files_are_available_without_account_access(client):
    page = client.get("/")
    assert page.status_code == 200 and "DELIVERY" in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert "tailwindcss.com" not in page.text and "iconify.design" not in page.text
    assert client.get("/assets/app.js").status_code == 200
    for name, path in dashboard.DOWNLOADS.items():
        response = client.get("/api/downloads/" + name)
        assert response.status_code == 200
        assert len(response.content) == Path(path).stat().st_size
