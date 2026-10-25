# Vercel frontend and Render API

Live website: **https://delivery-ops-mk.vercel.app/**

The static HTML, CSS, JavaScript and favicon are hosted on Vercel. The Python API,
read-only serving database, frozen planning data and native reports are hosted on
the Render free service at `https://delivery-ops-api.onrender.com`.

## Opening the website

The website HTML contains the complete approved connection screen. It renders
before an API reply and requires no server-side rendering or Python startup on
Vercel. Its Satoshi font uses `font-display: swap`; no external CSS import blocks
the initial interface.

The browser requests `/api/health` through a Vercel external rewrite. It accepts
only JSON reporting the expected Delivery Ops application, ready status and
source-order count. HTML startup pages, network errors and timeouts remain inside
the designed waiting flow; they never replace the website page.

After server readiness, metadata, overview, planning and evidence must all load
before the app is revealed. The elapsed counter measures real waiting time.
Startup retries use bounded backoff with a three-minute startup budget. Individual
health checks time out after at most 15 seconds; workspace requests have a maximum
20-second timeout, reduced to the remaining startup budget. Terminal failure stops
polling and offers Try again. Offline detection offers a matching message and
retries when the browser reports reconnection. No continuous keep-alive requests,
fake progress percentage, or fabricated ready state is used.

The waiting-to-dashboard transition respects reduced-motion settings. Deep-linked
sections are restored after data readiness, and both navigation menus continue to
track the main scroll container. Existing filters, solver bounds, fixed-evidence
cohorts and read-only data boundaries are retained.

## Configuration

- `dashboard/vercel.json`: static frontend configuration, same-origin `/api/*`
  forwarding, cache bypass and response headers. Deploy from **dashboard/**, not
  from the Python repository root. No database/model/report binary is uploaded as
  a Vercel frontend asset.
- `requirements-api.txt`: lean serving dependencies. The larger research lock
  remains separate.
- `.python-version` / Render `PYTHON_VERSION`: Python 3.13.15.
- `render.yaml`: reproducible free-service settings. The deployed service was
  created in the Render dashboard from the public Git repository, in Singapore,
  with `/api/health` and manual deploys.
- Render start command uses one worker, bounded concurrency, and one BLAS thread
  per numerical library. DuckDB connections are read-only, with two threads and a
  96 MB per-connection memory limit.

Vercel proxies only `/api/*` to the fixed Render origin. The browser keeps one
origin for API calls, exports and report downloads; no wildcard CORS permission
or browser-visible account credential is needed. API responses use `no-store`,
and Vercel rewrite caching is disabled to avoid retaining startup or failure pages.

## Updating

GitHub Actions verifies the project; it does not deploy either host. The Render
service has automatic deployment off. For backend changes, push the verified
commit, then choose Manual Deploy in Render. For frontend changes, deploy the
`dashboard/` directory with the existing Vercel project:

```text
vercel deploy --cwd dashboard --project delivery-ops --prod --scope mk00315
```

The friendly address is registered as a production project domain. Verify it
after publishing a new production deployment. The initial deployment also has
the Vercel production alias `https://delivery-ops-dusky.vercel.app`. Anonymous
HTTP requests to the friendly address were verified to return the app directly,
without a Vercel sign-in redirect.

## Verification and limits

The live HTTP checks cover static-asset byte parity, actual API health/data,
scoped CSV export, complete Excel/PBIX download hashes and the hosted constrained
optimizer. Browser checks cover the live filters, saved scenarios, deep links,
default restoration and console errors. The source passes 99 Python tests and
13 frontend startup/recovery tests, including GitHub Actions on Linux.

Waiting, timeout/retry and offline visuals were also checked with a controlled
localhost API. Its timeout was accelerated only inside the temporary QA fixture;
offline detection was simulated only inside that test page. These are controlled
failure tests, not a claim of observing Render's full idle spin-down interval.
Responsive checks used real browser viewports, not physical phone hardware.

Render free services can sleep after inactivity; Vercel does not remove the API
startup delay. This design keeps the website available and explains that wait.
See [Render's free-service documentation](https://render.com/docs/free) and
[Vercel's external rewrites documentation](https://vercel.com/docs/routing/rewrites).
The app does not keep itself artificially awake or add a paid service.

See `SPLIT_HOSTING_VERIFICATION.json` and `evidence/` for dated evidence. Original
Excel, model, dataset and cloud execution records remain separately preserved.
