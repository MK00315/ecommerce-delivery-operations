# Delivery Ops dashboard

The working dashboard follows the Midnight Editorial design selected and approved
by the user in Superdesign: dark surfaces, coral accents, Satoshi typography,
editorial headings, top navigation and a glass navigation dock.

## Start and stop

Double-click `START_Delivery_Dashboard.cmd` in the project folder. It starts the
server in the background and opens http://127.0.0.1:8125. Reopening the launcher
reuses an already running dashboard. `STOP_Delivery_Dashboard.cmd` stops the
instance owned by that launcher. Neither action changes Windows settings.

For a fresh checkout, create a Python 3.13 environment and install `requirements.txt`
as described in the root README. The verified serving snapshot, frozen review data
and native report files are bundled, so no raw-data download, model training,
cloud account or Colab session is needed to use the app. Original raw CSV files
and the larger working/training databases are excluded from Git.

From a terminal, readiness can be checked with
`./.venv/Scripts/python.exe run_delivery_dashboard.py --check`.
Run `run_delivery_dashboard.py --port 8125` to keep the server in that terminal.

## Use the overview and patterns

Select a customer state and inclusive purchase-date range, then Apply filters.
Reset restores all 99,441 original orders. Counts, delivery durations, monthly
trend, state volumes, distance groups and basket comparisons update together.
The displayed delivery rate divides late orders by eligible completed deliveries.
Orders with unsupported/unknown outcomes stay outside this denominator.

The count/rate chart toggle changes the monthly measure. Hover or focus a chart
point to see its late, eligible and total source counts. Empty filters retain
zero counts and show n/a for unavailable rates or durations. Export view downloads
the currently applied monthly summary as CSV; unapplied form changes do not change
the export's scope. The full Excel workbook and native Power BI report can be
downloaded from the footer when those local report files are present.

## Use the review planner

The planner has a separate fixed August 2018 approval cohort, independent of the
overview's purchase-date/state filters. Saved scenarios cover seven executed
capacity/time settings, four equally constrained policies and 28 daily batches.
Choose a scenario and either all batches or a single screening date. The default
120-minute setting queues 721 reviews, with 79 known late and 24 unknown outcomes,
using 3,314 minutes across the 28 batches.

Custom batch runs the actual existing mixed-integer optimizer for one selected
historical batch. Change pooled minutes, review count and primary-seller limit,
then Calculate batch. The four policies receive the same candidates and limits.
Allowed limits are 0-480 minutes, 0-60 reviews and 0-10 per primary seller. The
optimizer has a three-second solver limit. A time-limited feasible result is
labelled feasible, rather than optimal. Only one custom solve runs at a time.

Priority points show the actual objective: sum of within-batch ordinal model ranks.
The known late count is a retrospective diagnostic, not the optimizer's input or
objective. It can be smaller than another policy's observed late count despite
higher priority points. Unknown outcomes consume capacity. Expand the daily table
or queue to inspect results; the queue previews at most 25 orders. There is no
carryover and no real customer, courier or dispatch action.

## Evidence and limits

The Evidence section keeps the four statistical comparisons and model diagnosis
fixed. They are not re-estimated by overview filters. Statistics are exploratory,
purchase-month-adjusted associations with purchase-week clustered marginal
intervals and Holm-corrected p values. Model ranking gain is modest, updated August
is a reused diagnostic and absolute probabilities are unreliable. Neither queues
nor charts establish prevented delays, causal effects, savings or production
qualification.

## Data and execution

`build_dashboard_data.py` creates the compact analytical snapshot
`data/dashboard/delivery_dashboard.duckdb` and its manifest from the verified
reporting CSVs and saved operations/model artifacts. It retains all 99,441 orders,
all 6,590 review candidates and all saved selections; no data sample is used.
The original DuckDB, source CSVs, cloud tables, model and native reports are preserved.

At runtime FastAPI reads this snapshot with DuckDB in read-only mode. The snapshot
hash is checked when the server starts. SQL parameters are bound and accepted
states, dates, scenarios and solver limits are validated. The solver receives only
the six outcome-blind decision fields; historical outcomes are joined afterwards.
Filters and custom calculations are computed in memory and are not written to a
database. No upload or permanent user-record collection is part of this dashboard.

HTML, CSS, JavaScript, inline SVG charts and icons are served locally. The original
template's public Satoshi font and an Inter fallback are external font resources;
the app's data and interactions have no external UI-library/CDN dependency.
Reduced-motion preferences, keyboard focus, chart point descriptions, labelled
controls and responsive layouts are included. Wide/mobile browser viewport checks
are CSS-layout checks, not claims of testing on physical phones.

## Rebuild and verification

After the verified foundation, model, operations and reporting exports exist, run:

```powershell
.\.venv\Scripts\python.exe build_dashboard_data.py
.\.venv\Scripts\python.exe run_delivery_dashboard.py --check
.\.venv\Scripts\python.exe -m pytest tests -q
```

Stop a running dashboard before replacing its snapshot on Windows. The builder
checks input hashes, order identities, cohort counts, saved planner totals and
selection membership before replacing the web snapshot. It does not retrain a model
or run cloud compute. Current verification and browser evidence are recorded in
`DASHBOARD_VERIFICATION.json` and `outputs/Delivery_Dashboard/`.

GitHub and live hosting remain the subsequent publication stage. The localhost
address works on this laptop while its server runs; it is not a public live link.

References: [FastAPI static files](https://fastapi.tiangolo.com/tutorial/static-files/),
[SciPy mixed-integer optimization](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html),
[Olist public dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce).
