"""Delivery Ops: read-only SQL analytics and bounded historical review planning."""
from contextlib import contextmanager
from datetime import date
from functools import lru_cache
import csv
import hashlib
import io
import json
from pathlib import Path
import threading
from typing import Annotated, Literal

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from threadpoolctl import threadpool_limits

from delivery_planner import DECISION_COLUMNS, ReviewLimits, evaluate_selected, greedy_selection, optimize_reviews

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data/dashboard"
DATABASE = DATA / "delivery_dashboard.duckdb"
MANIFEST = json.loads((DATA / "snapshot_manifest.json").read_text())
if hashlib.sha256(DATABASE.read_bytes()).hexdigest() != MANIFEST["snapshot_sha256"]:
    raise ValueError("The dashboard snapshot hash differs from its manifest; rebuild the verified snapshot.")
POLICIES = {"optimized": "Constrained optimizer", "risk_first": "Highest risk first",
            "priority_per_minute": "Priority per minute", "oldest_first": "Oldest approval first"}
SOLVER_SLOT = threading.BoundedSemaphore(1)


@contextmanager
def connection():
    con = duckdb.connect(str(DATABASE), read_only=True, config={"threads": 2})
    try:
        yield con
    finally:
        con.close()


def records(con, sql, parameters=()):
    # Pandas converts SQL nulls, dates and non-finite display values to valid JSON.
    return json.loads(con.execute(sql, parameters).df().to_json(orient="records", date_format="iso", double_precision=15))


@lru_cache(maxsize=1)
def metadata():
    with connection() as con:
        dates = con.execute("SELECT min(purchase_date),max(purchase_date) FROM orders").fetchone()
        states = [r[0] for r in con.execute("SELECT DISTINCT customer_state FROM orders ORDER BY 1").fetchall()]
        scenarios = records(con, """SELECT scenario,capacity_minutes,cost_multiplier FROM scenario_saved
            WHERE policy='optimized' ORDER BY capacity_minutes,cost_multiplier""")
        batches = [r[0].date().isoformat() for r in con.execute("SELECT DISTINCT batch_cutoff FROM review_candidates ORDER BY 1").fetchall()]
    return {"name": "Delivery Ops", "source": "Historical public Olist data", "source_url": "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce",
            "start": dates[0].isoformat(), "end": dates[1].isoformat(), "states": states,
            "scenarios": scenarios, "batches": batches, "default_scenario": "capacity_120_cost_1",
            "source_orders": 99441, "model_is_experimental": True, "snapshot_built_at": MANIFEST["built_at"],
            "operations_run": MANIFEST["operations_run"], "downloads": {k: p.is_file() for k, p in DOWNLOADS.items()}}


def scope(state="ALL", start=None, end=None):
    meta = metadata()
    if state != "ALL" and state not in meta["states"]:
        raise HTTPException(422, "Choose a customer state from the available list.")
    first, last = date.fromisoformat(meta["start"]), date.fromisoformat(meta["end"])
    start, end = start or first, end or last
    if start > end:
        raise HTTPException(422, "The start date must be on or before the end date.")
    if start < first or end > last:
        raise HTTPException(422, "Choose purchase dates within the historical snapshot.")
    where, parameters = "purchase_date BETWEEN ? AND ?", [start, end]
    if state != "ALL":
        where += " AND customer_state=?"
        parameters.append(state)
    return where, parameters, {"state": state, "start": start.isoformat(), "end": end.isoformat()}


@lru_cache(maxsize=128)
def view_data(state, start, end):
    where, params, selected = scope(state, start, end)
    with connection() as con:
        metric = records(con, f"""SELECT count(*) orders,count(*) FILTER(WHERE sla_eligible) eligible,
            count(*) FILTER(WHERE is_late) late,count(*) FILTER(WHERE NOT sla_eligible) outside_cohort,
            count(*) FILTER(WHERE sla_eligible AND NOT is_late) on_time,
            count(*) FILTER(WHERE is_late)*1.0/nullif(count(*) FILTER(WHERE sla_eligible),0) late_rate,
            avg(delivery_days) mean_days,median(delivery_days) median_days,
            count(*) FILTER(WHERE sla_eligible AND distance_complete)*1.0/nullif(count(*) FILTER(WHERE sla_eligible),0) distance_coverage
            FROM orders WHERE {where}""", params)[0]
        monthly = records(con, f"""WITH selected AS (SELECT * FROM orders WHERE {where}),
            grouped AS (SELECT date_trunc('month',purchase_date)::DATE AS month_start,count(*) orders,
                count(*) FILTER(WHERE sla_eligible) eligible,count(*) FILTER(WHERE is_late) late
                FROM selected GROUP BY 1),
            calendar AS (SELECT unnest(generate_series(date_trunc('month',?::DATE),date_trunc('month',?::DATE),interval 1 month))::DATE AS month_start)
            SELECT c.month_start AS "month",coalesce(g.orders,0) orders,coalesce(g.eligible,0) eligible,coalesce(g.late,0) late,
                   g.late*1.0/nullif(g.eligible,0) late_rate FROM calendar c LEFT JOIN grouped g USING(month_start) ORDER BY c.month_start""",
            [*params, selected["start"], selected["end"]])
        states = records(con, f"""SELECT customer_state state,count(*) orders,
            count(*) FILTER(WHERE sla_eligible) eligible,count(*) FILTER(WHERE is_late) late,
            count(*) FILTER(WHERE is_late)*1.0/nullif(count(*) FILTER(WHERE sla_eligible),0) late_rate,
            avg(delivery_days) mean_days FROM orders WHERE {where} GROUP BY 1 ORDER BY eligible DESC,state""", params)
        groups = {}
        for name in ["distance", "basket"]:
            column = name + "_group"
            groups[name] = records(con, f"""SELECT {column} AS "name",count(*) orders,
                count(*) FILTER(WHERE sla_eligible) eligible,count(*) FILTER(WHERE is_late) late,
                count(*) FILTER(WHERE is_late)*1.0/nullif(count(*) FILTER(WHERE sla_eligible),0) late_rate
                FROM orders WHERE {where} GROUP BY 1 ORDER BY 1""", params)
    return {"scope": selected, "metrics": metric, "monthly": monthly, "states": states, **groups,
            "source_orders": 99441, "sampled": False}


def validate_plan(scenario, batch):
    if scenario not in {s["scenario"] for s in metadata()["scenarios"]}:
        raise HTTPException(422, "Choose an executed scenario.")
    if batch != "all" and batch not in metadata()["batches"]:
        raise HTTPException(422, "Choose an available August screening batch.")


@lru_cache(maxsize=64)
def planning_data(scenario, batch):
    validate_plan(scenario, batch)
    where, params = "scenario=?", [scenario]
    if batch != "all":
        where += " AND cast(batch_cutoff AS DATE)=?"
        params.append(batch)
    with connection() as con:
        summary = records(con, f"""SELECT policy,max(capacity_minutes) capacity_minutes,max(cost_multiplier) cost_multiplier,
            count(*) batches,sum(selected_orders) selected_orders,sum(used_minutes) used_minutes,
            sum(selected_unknown_outcomes) selected_unknown_outcomes,sum(selected_known_late) selected_known_late,
            sum(selected_known_outcomes) selected_known_outcomes,sum(priority_points) priority_points,
            sum(candidate_orders) candidate_orders,sum(candidate_known_late) candidate_known_late,
            sum(candidate_unknown_outcomes) candidate_unknown_outcomes,sum(unused_minutes) unused_minutes,
            bool_and(coalesce(optimal,false)) all_batches_optimal
            FROM daily_saved WHERE {where} GROUP BY policy""", params)
        daily = records(con, f"""SELECT cast(batch_cutoff AS DATE) screening_date,selected_orders,used_minutes,
            selected_unknown_outcomes,selected_known_late,priority_points,optimal
            FROM daily_saved WHERE {where} AND policy='optimized' ORDER BY batch_cutoff""", params)
    result = {r["policy"]: {**r, "name": POLICIES[r["policy"]]} for r in summary}
    return {"scenario": scenario, "batch": batch, "policies": [result[p] for p in POLICIES], "daily": daily,
            "limits": {"maximum_reviews": 30, "per_primary_seller": 5}, "scope": "Saved August 2018 approval replay; independent of overview purchase filters"}


def queue_rows(con, ids):
    if not ids:
        return []
    return records(con, """SELECT c.order_id,c.approved_at,c.primary_seller_id,c.priority_points,c.review_minutes,
             o.customer_state,coalesce(CASE y.observed_label_by_cutoff WHEN 1 THEN 'Known late' WHEN 0 THEN 'Known on time' END,'Unknown') outcome
             FROM review_candidates c LEFT JOIN orders o USING(order_id) LEFT JOIN outcomes y USING(order_id)
             WHERE c.order_id IN (SELECT unnest(?::VARCHAR[])) ORDER BY priority_points DESC,c.order_id LIMIT 25""", [ids])


class CustomPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch: date
    minutes: Annotated[int, Field(strict=True, ge=0, le=480)] = 120
    maximum_reviews: Annotated[int, Field(strict=True, ge=0, le=60)] = 30
    per_primary_seller: Annotated[int, Field(strict=True, ge=0, le=10)] = 5


@lru_cache(maxsize=64)
def custom_plan(batch, minutes, maximum_reviews, per_primary_seller):
    if batch not in metadata()["batches"]:
        raise HTTPException(422, "Choose an available historical screening batch.")
    with connection() as con:
        # The solver receives the exact six-column allowlist, with no outcome join.
        candidates = con.execute("SELECT * FROM review_candidates WHERE cast(batch_cutoff AS DATE)=? ORDER BY order_id", [batch]).df()[DECISION_COLUMNS]
        outcomes = con.execute("SELECT * FROM outcomes").df()
    limits = ReviewLimits(minutes, maximum_reviews, per_primary_seller, solver_seconds=3.0)
    with threadpool_limits(limits=1):
        optimized_ids, optimized_info = optimize_reviews(candidates, limits)
        policies = [("optimized", optimized_ids, optimized_info)]
        policies += [(name, *greedy_selection(candidates, limits, name)) for name in list(POLICIES)[1:]]
    rows = [{"policy": name, "name": POLICIES[name], **info, **evaluate_selected(candidates, ids, outcomes)}
            for name, ids, info in policies]
    with connection() as con:
        queue = queue_rows(con, optimized_ids)
    return {"batch": batch, "limits": {"minutes": minutes, "maximum_reviews": maximum_reviews,
            "per_primary_seller": per_primary_seller}, "policies": rows, "queue": queue,
            "queue_preview_limit": 25, "solver": {"optimal": optimized_info["optimal"], "status": optimized_info["status"],
            "gap": optimized_info["solver_gap"], "seconds_limit": 3},
            "saved": False, "model_retrained": False, "scope": "One historical batch; outcomes joined after selection"}


DOWNLOADS = {"excel": ROOT / "reports/native/Delivery_Operations.xlsx",
             "powerbi": ROOT / "reports/native/Ecommerce_Delivery_Operations.pbix"}

app = FastAPI(title="Delivery Ops", version="1.0.0", docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")


@app.middleware("http")
async def response_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com https://vgbujcuwptvheqijyjbe.supabase.co; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health():
    return {"status": "ready", "source_orders": 99441, "snapshot_sha256": MANIFEST["snapshot_sha256"],
            "operations_run": MANIFEST["operations_run"], "application": "delivery-ops"}


@app.get("/api/meta")
def meta():
    return metadata()


@app.get("/api/view")
def view(state: str = Query("ALL", pattern=r"^(ALL|[A-Z]{2})$"), start: date | None = None, end: date | None = None):
    return view_data(state, start, end)


@app.get("/api/planning")
def planning(scenario: str = "capacity_120_cost_1", batch: str = "all"):
    return planning_data(scenario, batch)


@app.get("/api/planning/queue")
def saved_queue(scenario: str = "capacity_120_cost_1", batch: str = "all", policy: Literal["optimized", "risk_first", "priority_per_minute", "oldest_first"] = "optimized"):
    validate_plan(scenario, batch)
    where, params = "scenario=? AND policy=?", [scenario, policy]
    if batch != "all":
        where += " AND cast(batch_cutoff AS DATE)=?"
        params.append(batch)
    with connection() as con:
        ids = [r[0] for r in con.execute(f"SELECT order_id FROM saved_selections WHERE {where}", params).fetchall()]
        return {"total": len(ids), "limit": 25, "rows": queue_rows(con, ids), "outcome_scope": "Retrospective, not used for selection"}


@app.post("/api/planning/custom")
def solve_plan(settings: CustomPlan):
    if not SOLVER_SLOT.acquire(blocking=False):
        raise HTTPException(429, "A custom plan is already running. Try again shortly.")
    try:
        return custom_plan(settings.batch.isoformat(), settings.minutes, settings.maximum_reviews, settings.per_primary_seller)
    except RuntimeError as error:
        raise HTTPException(503, "The solver did not return a verified feasible plan. Adjust the limits and retry.") from error
    finally:
        SOLVER_SLOT.release()


@app.get("/api/evidence")
def evidence():
    return {"statistics": MANIFEST["statistics"], "model": MANIFEST["model"],
            "operations_run": MANIFEST["operations_run"], "model_run": MANIFEST["model_run"],
            "cloud_path": "Azure Data Factory â†’ verified local handoff â†’ Databricks Delta",
            "compute": "Training, statistical analysis and planning ran locally with Python.",
            "data_boundary": "Read-only snapshot; no live Azure/Databricks refresh or user-input persistence."}


@app.get("/api/export")
def export(state: str = Query("ALL", pattern=r"^(ALL|[A-Z]{2})$"), start: date | None = None, end: date | None = None):
    data = view_data(state, start, end)
    text = io.StringIO(newline="")
    writer = csv.writer(text)
    writer.writerow(["Purchase month", "Customer state filter", "Source orders", "Eligible deliveries", "Late deliveries", "Late rate"])
    for row in data["monthly"]:
        writer.writerow([row["month"][:10], state, row["orders"], row["eligible"], row["late"], row["late_rate"]])
    filename = f"Delivery_{state}_{data['scope']['start']}_{data['scope']['end']}.csv"
    return Response("\ufeff" + text.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/downloads/{kind}")
def download(kind: Literal["excel", "powerbi"]):
    path = DOWNLOADS[kind]
    if not path.is_file():
        raise HTTPException(404, "This report file is not installed in the current deployment.")
    return FileResponse(path, filename=path.name)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "dashboard/index.html", headers={"Cache-Control": "no-cache"})


app.mount("/assets", StaticFiles(directory=ROOT / "dashboard/assets"), name="assets")
