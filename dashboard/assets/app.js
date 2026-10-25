"use strict";

const $ = id => document.getElementById(id);
const appState = { meta: null, view: null, trend: "count", mode: "saved", request: 0, planRequest: 0, abort: null, planAbort: null };
const nf = new Intl.NumberFormat("en-US");
const num = n => n === null || n === undefined ? "n/a" : nf.format(n);
const pct = n => n === null || n === undefined ? "n/a" : `${(n * 100).toFixed(2)}%`;
const fixed = (n, digits = 2) => n === null || n === undefined ? "n/a" : Number(n).toFixed(digits);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const shortDate = value => String(value).slice(0, 10);
const dateLabel = value => new Date(`${shortDate(value)}T00:00:00`).toLocaleDateString("en-GB", {day:"2-digit", month:"short", year:"numeric"});
const monthLabel = (value, year = false) => new Date(`${shortDate(value)}T00:00:00`).toLocaleDateString("en-GB", {month:"short", ...(year ? {year:"2-digit"} : {})});

async function api(path, options = {}) {
  return window.DeliveryConnection.request(path, options);
}

function notice(id, message = "", error = false, retry = null) {
  const el = $(id); el.replaceChildren(); el.hidden = !message;
  el.classList.toggle("error", error);
  if (!message) return;
  el.append(document.createTextNode(message));
  if (retry) { const b = document.createElement("button"); b.type = "button"; b.textContent = "Retry"; b.addEventListener("click", retry); el.append(b); }
}

function queryScope() {
  return new URLSearchParams({state: $("state-filter").value, start: $("start-filter").value, end: $("end-filter").value});
}

async function loadView() {
  const number = ++appState.request;
  appState.abort?.abort(); appState.abort = new AbortController();
  $("view-filters").setAttribute("aria-busy", "true"); $("apply-filters").disabled = true;
  $("view-metrics").classList.add("data-loading");
  notice("app-notice", "Updating the selected historical cohort…");
  try {
    const data = await api(`/api/view?${queryScope()}`, {signal: appState.abort.signal});
    if (number !== appState.request) return;
    appState.view = data; renderView(); notice("app-notice");
    if (!data.metrics.orders) notice("app-notice", "No source orders match these filters. Choose another date range or reset to all data.");
    return true;
  } catch (error) {
    if (error.name !== "AbortError" && number === appState.request) notice("app-notice", `${error.message}${appState.view ? " The previous view is still shown." : ""}`, true, loadView);
    return false;
  } finally {
    if (number === appState.request) { $("apply-filters").disabled = false; $("view-filters").setAttribute("aria-busy", "false"); $("view-metrics").classList.remove("data-loading"); }
  }
}

function renderView() {
  const data = appState.view, m = data.metrics;
  $("metric-orders").textContent = num(m.orders); $("metric-eligible").textContent = num(m.eligible);
  $("metric-rate").textContent = pct(m.late_rate); $("metric-days").innerHTML = `${fixed(m.mean_days)}${m.mean_days === null ? "" : "<small>days</small>"}`;
  $("orders-sub").textContent = data.scope.state === "ALL" ? "In the selected purchase-date range" : `Customer state ${data.scope.state} · selected dates`;
  $("rate-sub").textContent = `${num(m.late)} late / ${num(m.eligible)} eligible deliveries`;
  $("days-sub").textContent = m.eligible ? `Median ${fixed(m.median_days)} days · eligible deliveries` : "No eligible delivery-time observations";
  const full = data.scope.state === "ALL" && data.scope.start === appState.meta.start && data.scope.end === appState.meta.end;
  $("view-scope").textContent = full ? "Full historical dataset." : `${data.scope.state === "ALL" ? "All states" : data.scope.state} · ${dateLabel(data.scope.start)} – ${dateLabel(data.scope.end)}.`;
  $("outside-cohort").innerHTML = `<strong>${num(m.outside_cohort)} orders</strong> outside the completed delivery-rate denominator`;
  $("export-view").href = `/api/export?${new URLSearchParams(data.scope)}`;
  $("trend-period").textContent = `Observed completed-order outcomes · ${dateLabel(data.scope.start)} – ${dateLabel(data.scope.end)}`;
  renderTrend(); renderStates();
  renderGroup("distance-bars", data.distance, ["Up to 500 km", "500-1,000 km", "1,000-2,000 km", "Over 2,000 km", "Unknown / incomplete"]);
  renderGroup("basket-bars", data.basket, ["1 item", "2-3 items", "4+ items", "Missing basket"]);
  $("distance-coverage").textContent = `${pct(m.distance_coverage)} of eligible baskets have complete distance coverage. Missing or partial geography stays separate.`;
}

function svgNode(tag, attrs = {}, value = null) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, attr] of Object.entries(attrs)) node.setAttribute(key, String(attr));
  if (value !== null) node.textContent = value;
  return node;
}

function niceMaximum(value) {
  if (!(value > 0)) return 1;
  const base = 10 ** Math.floor(Math.log10(value));
  const scale = value / base;
  return (scale <= 1 ? 1 : scale <= 2 ? 2 : scale <= 5 ? 5 : 10) * base;
}

function renderTrend() {
  if (!appState.view) return;
  const host = $("trend-chart"), rows = appState.view.monthly, rate = appState.trend === "rate";
  host.replaceChildren(); $("trend-count").setAttribute("aria-pressed", String(!rate)); $("trend-rate").setAttribute("aria-pressed", String(rate));
  $("trend-heading").textContent = rate ? "Late rate by purchase month" : "Late deliveries by purchase month";
  if (!appState.view.metrics.orders) { host.innerHTML = '<div class="empty-chart">No orders in this date and state cohort.<br>Reset the filters to explore the full dataset.</div>'; $("trend-insight").textContent = "No observed source orders"; return; }
  if (rate && !appState.view.metrics.eligible) { host.innerHTML = '<div class="empty-chart">No eligible completed deliveries in this cohort.<br>Monthly late rates are unavailable; unknown outcomes are not on-time deliveries.</div>'; $("trend-insight").textContent = "No eligible outcomes for a delivery-rate denominator"; return; }
  const W = Math.max(270, Math.round(host.clientWidth - 44)), H = 228;
  const left = rate ? 41 : 43, right = W - 12, top = 21, bottom = H - 32;
  const getValue = row => rate ? row.late_rate : row.late;
  const values = rows.map(getValue).filter(value => value !== null);
  const maximum = niceMaximum(Math.max(0, ...values));
  const max = rate ? maximum : Math.max(4, Math.ceil(maximum / 4) * 4);
  const x = i => rows.length === 1 ? (left + right) / 2 : left + i * (right - left) / (rows.length - 1);
  const y = value => bottom - value * (bottom - top) / max;
  const svg = svgNode("svg", {viewBox: `0 0 ${W} ${H}`, class: "trend", role: "img", "aria-label": `${rate ? "Late rate" : "Late order count"} by purchase month for the selected cohort`});
  const grad = svgNode("linearGradient", {id: "live-trend-fill", x1: "0", y1: "0", x2: "0", y2: "1"});
  grad.append(svgNode("stop", {offset:"0%", "stop-color":"#FF6B50", "stop-opacity": .18}), svgNode("stop", {offset:"100%", "stop-color":"#FF6B50", "stop-opacity": 0}));
  const defs = svgNode("defs"); defs.append(grad); svg.append(defs);
  for (let i = 0; i <= 4; i++) {
    const value = max * i / 4, yy = y(value);
    svg.append(svgNode("line", {x1:left,y1:yy,x2:right,y2:yy,stroke:"#222222"}));
    svg.append(svgNode("text", {x:left-9,y:yy+3,fill:"#888888","font-size":10,"text-anchor":"end"}, rate ? `${(value*100).toFixed(value < .1 ? 1 : 0)}%` : nf.format(value)));
  }
  let segment = [], segments = [];
  rows.forEach((row, i) => { if (getValue(row) === null) { if (segment.length) segments.push(segment); segment=[]; } else segment.push([x(i), y(getValue(row))]); });
  if (segment.length) segments.push(segment);
  for (const points of segments) {
    const line = points.map((p,i) => `${i ? "L" : "M"}${p[0].toFixed(2)} ${p[1].toFixed(2)}`).join("");
    if (points.length > 1) svg.append(svgNode("path", {d: `${line}L${points.at(-1)[0]} ${bottom}H${points[0][0]}Z`, fill:"url(#live-trend-fill)"}));
    svg.append(svgNode("path", {d:line,fill:"none",stroke:"#FF6B50","stroke-width":2.3,"stroke-linejoin":"round","stroke-linecap":"round"}));
  }
  const every = Math.max(1, Math.ceil(rows.length / Math.max(3, Math.floor((right-left)/70))));
  const multiYear = rows.length > 12 || rows[0]?.month.slice(0,4) !== rows.at(-1)?.month.slice(0,4);
  const tickIndices = rows.map((_,i)=>i).filter(i=>i%every===0);
  const last = rows.length - 1;
  if (tickIndices.at(-1) !== last) {
    if (tickIndices.length > 1 && x(last)-x(tickIndices.at(-1)) < 55) tickIndices.pop();
    tickIndices.push(last);
  }
  for (const i of tickIndices) svg.append(svgNode("text", {x:x(i),y:H-8,fill:"#888888","font-size":10,"text-anchor":"middle"}, monthLabel(rows[i].month, multiYear)));
  const tooltip = document.createElement("div"); tooltip.className="chart-tooltip"; tooltip.hidden=true; tooltip.setAttribute("role","tooltip");
  rows.forEach((row, i) => {
    if (getValue(row) === null) return;
    const label = `${monthLabel(row.month, true)}: ${rate ? pct(row.late_rate) : `${num(row.late)} late`}; ${num(row.eligible)} eligible of ${num(row.orders)} source orders`;
    const point = svgNode("circle", {cx:x(i),cy:y(getValue(row)),r: rows.length > 15 ? 3 : 3.7,fill:"#111111",stroke:"#FF6B50","stroke-width":1.8,tabindex:0,"aria-label":label});
    const show = () => {
      tooltip.replaceChildren(); const title=document.createElement("strong"); title.textContent=monthLabel(row.month,true); tooltip.append(title,document.createTextNode(`${num(row.late)} late · ${pct(row.late_rate)}`),document.createElement("br"),document.createTextNode(`${num(row.eligible)} eligible / ${num(row.orders)} orders`));
      const rect=point.getBoundingClientRect(), parent=host.getBoundingClientRect(); tooltip.hidden=false;
      tooltip.style.left=`${Math.max(0, Math.min(host.clientWidth-190, rect.left-parent.left-60))}px`; tooltip.style.top=`${Math.max(0, rect.top-parent.top-72)}px`;
    };
    point.addEventListener("mouseenter",show); point.addEventListener("focus",show);
    point.addEventListener("mouseleave",()=>{tooltip.hidden=true;}); point.addEventListener("blur",()=>{tooltip.hidden=true;});
    svg.append(point);
  });
  host.append(svg,tooltip);
  if (rate) $("trend-insight").textContent = "Rates use completed eligible orders. Check cohort sizes on focus or hover.";
  else {
    const peak=rows.reduce((a,b)=>a.late>=b.late?a:b);
    $("trend-insight").innerHTML=`<strong>${esc(monthLabel(peak.month,true))}: ${num(peak.late)}</strong> observed late deliveries`;
  }
}

function renderStates() {
  const rows=appState.view.states.slice(0,6), max=Math.max(1,...rows.map(r=>r.eligible));
  $("state-bars").innerHTML=rows.length ? rows.map((r,i)=>`<div><div class="state-label"><span>${esc(r.state)}</span><span>${num(r.eligible)}</span></div><div class="state-track"><div class="state-fill" style="width:${r.eligible/max*100}%;opacity:${1-i*.1}"></div></div></div>`).join("") : '<div class="muted-text">No state observations match the filters.</div>';
}

function renderGroup(id, rows, order) {
  const sorted=[...rows].sort((a,b)=>order.indexOf(a.name)-order.indexOf(b.name));
  const max=Math.max(.01,...sorted.map(r=>r.late_rate||0));
  $(id).innerHTML=sorted.length ? sorted.map(r=>`<div><div class="group-bar-head"><span>${esc(r.name)}<small>${num(r.eligible)} eligible</small></span><strong>${pct(r.late_rate)}</strong></div><div class="state-track"><div class="state-fill" style="width:${(r.late_rate||0)/max*100}%;${r.name.startsWith("Unknown")?"background:#888888":""}"></div></div></div>`).join("") : '<div class="muted-text">No group observations in this cohort.</div>';
}

function setMode(mode) {
  appState.mode=mode; ++appState.planRequest; appState.planAbort?.abort();
  $("saved-mode").setAttribute("aria-pressed",String(mode==="saved")); $("custom-mode").setAttribute("aria-pressed",String(mode==="custom"));
  $("saved-plan-form").hidden=mode!=="saved"; $("custom-plan-form").hidden=mode!=="custom"; $("daily-detail").hidden=mode!=="saved";
  notice("planner-notice");
  if(mode==="saved") loadSavedPlan();
  else { $("plan-status").textContent=""; runCustomPlan(); }
}

function renderPolicies(rows, options) {
  const optimized=rows.find(r=>r.policy==="optimized");
  $("plan-reviews").textContent=num(optimized.selected_orders); $("plan-known-late").textContent=num(optimized.selected_known_late); $("plan-unknown").textContent=num(optimized.selected_unknown_outcomes);
  $("plan-kind").textContent=options.custom ? "Custom batch · constrained optimizer" : "Saved replay · constrained optimizer";
  $("plan-caption").textContent=`${options.custom ? dateLabel(options.batch) : `${num(optimized.batches)} historical screening ${optimized.batches===1?"batch":"batches"}`} · ${num(optimized.candidate_orders)} candidates. Review durations are illustrative.`;
  $("policy-rows").innerHTML=rows.map(r=>`<tr><td class="policy-name">${esc(r.name)}</td><td>${num(r.selected_orders)}</td><td>${num(r.used_minutes)}</td><td>${num(Number(r.priority_points.toFixed(1)))}</td><td>${num(r.selected_known_late)}</td></tr>`).join("");
  $("plan-limits").innerHTML=`<div class="limit">${num(options.minutes)} min <span>/ batch</span></div><div class="limit">${num(options.count)} reviews <span>max / batch</span></div><div class="limit">${num(options.seller)} <span>max / primary seller</span></div>${!options.custom&&optimized.cost_multiplier!==1?`<div class="limit">${fixed(optimized.cost_multiplier)}× <span>review time</span></div>`:""}`;
  $("plan-total-scope").textContent=options.custom ? "Totals cover one selected historical batch." : `Minutes and review totals cover ${num(optimized.batches)} selected ${optimized.batches===1?"batch":"batches"}.`;
  $("plan-badge").textContent=options.optimal ? "Optimal priority allocation" : "Feasible · time limit";
}

function renderQueue(data) {
  const rows=data.rows || data.queue || [];
  const total=data.total ?? data.policies?.find(r=>r.policy==="optimized")?.selected_orders ?? rows.length;
  $("queue-summary").textContent=`Inspect optimized review queue · ${num(total)} selected · first 25 shown`;
  $("queue-rows").innerHTML=rows.length ? rows.map(r=>`<tr><td class="order-ref" title="${esc(r.order_id)}">${esc(r.order_id.slice(0,10))}…</td><td>${fixed(r.priority_points,1)}</td><td>${num(r.review_minutes)}</td><td>${esc(r.customer_state||"Unknown")}</td><td class="${r.outcome==="Unknown"?"unknown":""}">${esc(r.outcome)}</td></tr>`).join("") : '<tr><td class="empty-cell" colspan="5">No orders selected under these limits.</td></tr>';
}

async function loadSavedPlan() {
  if(!appState.meta||appState.mode!=="saved") return;
  const request=++appState.planRequest; appState.planAbort?.abort(); appState.planAbort=new AbortController();
  const params=new URLSearchParams({scenario:$("scenario-filter").value,batch:$("batch-filter").value});
  $("plan-status").textContent="Loading saved scenario…"; notice("planner-notice");
  try {
    const [data,queue]=await Promise.all([api(`/api/planning?${params}`,{signal:appState.planAbort.signal}),api(`/api/planning/queue?${params}`,{signal:appState.planAbort.signal})]);
    if(request!==appState.planRequest||appState.mode!=="saved") return;
    const opt=data.policies.find(r=>r.policy==="optimized");
    renderPolicies(data.policies,{custom:false,batch:data.batch,minutes:opt.capacity_minutes,count:30,seller:5,optimal:opt.all_batches_optimal}); renderQueue(queue);
    $("daily-rows").innerHTML=data.daily.map(r=>`<tr><td>${esc(dateLabel(r.screening_date))}</td><td>${num(r.selected_orders)}</td><td>${num(r.used_minutes)}</td><td>${num(r.selected_unknown_outcomes)}</td><td>${num(r.selected_known_late)}</td></tr>`).join("");
    $("plan-status").textContent=`${num(opt.batches)} saved ${opt.batches===1?"batch":"batches"} · no reoptimization`;
    return true;
  } catch(error) { if(error.name!=="AbortError"&&request===appState.planRequest) { $("plan-status").textContent="Scenario not updated"; notice("planner-notice",`${error.message} Previous planning results remain visible.`,true,loadSavedPlan); } }
  return false;
}

async function runCustomPlan() {
  if(!appState.meta||appState.mode!=="custom"||!$("custom-plan-form").reportValidity()) return;
  const request=++appState.planRequest; $("run-plan").disabled=true; $("run-plan").textContent="Calculating…";
  notice("planner-notice","Solving one historical batch under the selected limits…");
  const body={batch:$("custom-batch").value,minutes:Number($("custom-minutes").value),maximum_reviews:Number($("custom-count").value),per_primary_seller:Number($("custom-seller").value)};
  try {
    const data=await api("/api/planning/custom",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    if(request!==appState.planRequest||appState.mode!=="custom") return;
    renderPolicies(data.policies,{custom:true,batch:data.batch,minutes:data.limits.minutes,count:data.limits.maximum_reviews,seller:data.limits.per_primary_seller,optimal:data.solver.optimal}); renderQueue(data);
    notice("planner-notice",data.solver.optimal ? "Calculation complete. The selected queue meets the time, review-count and primary-seller limits." : "A feasible queue was found within the time limit. Optimality is not established for this custom calculation.");
  } catch(error) { if(request===appState.planRequest) notice("planner-notice",`${error.message} Previous planning results remain visible.`,true,runCustomPlan); }
  finally { $("run-plan").disabled=false; $("run-plan").textContent="Calculate batch"; }
}

function renderEvidence(data) {
  const sign=n=>`${n>=0?"+":""}${(n*100).toFixed(2)}`;
  $("stat-rows").innerHTML=data.statistics.map(r=>`<tr><td>${esc(r.label)}</td><td>${sign(r.adjusted_difference)} pp</td><td>${sign(r.ci_low)} to ${sign(r.ci_high)}</td><td>${Number(r.holm_p_value).toExponential(2)}</td></tr>`).join("");
  const model=data.model,d=model.diagnostic;
  $("method-notes").innerHTML=`<p><strong>Data path:</strong> ${esc(data.cloud_path)}. ${esc(data.compute)}</p><p><strong>Source:</strong> all 99,441 Olist orders are retained; delivery rates use only eligible observed completed deliveries. An estimated calendar date covers its full day. Unknown outcomes are not on-time labels.</p><p><strong>Model:</strong> static logistic regression, ${num(model.inputs)} inputs, ${num(model.final_fit_orders)} refit orders. Updated August average precision ${fixed(d.average_precision,4)}, ROC-AUC ${fixed(d.roc_auc,4)} and adjusted Brier score ${fixed(d.brier_score,4)}. Adjusted probabilities are less reliable than raw/constant baselines in this reused diagnostic.</p><p><strong>Planning:</strong> previous-day approvals are screened at 09:00. Only completions already recorded before that cutoff are removed. The solver receives order IDs, approvals, cutoff, primary seller, ordinal priority and assumed review minutes. Outcomes are joined after selection. Each order is offered once, with no carryover. Time assumes 4 base minutes, +2 multiple items, +3 multiple sellers and +1 interstate/unknown.</p><p><strong>Statistical scope:</strong> exploratory purchase-month-adjusted associations, purchase-week clustered marginal intervals and Holm correction over four tests. Group selection and incomplete observation limit interpretation.</p><p><strong>Application:</strong> ${esc(data.data_boundary)} Custom plans use frozen scores and do not retrain the model.</p>`;
}

const navigationScroller = document.querySelector("main.shell");
const navigationSections = ["overview", "patterns", "review-planner", "evidence"].map($);
const navigationLinks = document.querySelectorAll(".nav-links a,.dock-link");
let navigationFrame = 0;
let initialNavigationPending = true;

function updateNavigation() {
  if ($("workspace").hidden) return;
  // The content scrolls inside main, while the header and dock stay in place.
  const inset = parseFloat(getComputedStyle(navigationScroller).scrollPaddingTop) || 0;
  const boundary = navigationScroller.getBoundingClientRect().top + inset + 1;
  let current = navigationSections[0];
  for (const section of navigationSections) {
    if (section.getBoundingClientRect().top <= boundary) current = section;
  }
  // A short final section can reach the end before its heading reaches the inset.
  const remaining = navigationScroller.scrollHeight - navigationScroller.clientHeight - navigationScroller.scrollTop;
  if (navigationScroller.scrollTop > 0 && remaining <= 2) current = navigationSections.at(-1);
  navigationLinks.forEach(link => {
    const selected = link.getAttribute("href") === `#${current.id}`;
    link.classList.toggle("active", selected);
    if (selected) link.setAttribute("aria-current", "location"); else link.removeAttribute("aria-current");
  });
}

function scheduleNavigation() {
  if (navigationFrame) return;
  navigationFrame = requestAnimationFrame(() => { navigationFrame = 0; updateNavigation(); });
}

navigationScroller.addEventListener("scroll", scheduleNavigation, {passive: true});
for (const event of ["wheel", "touchstart", "keydown", "pointerdown"]) {
  navigationScroller.addEventListener(event, () => { initialNavigationPending = false; }, {passive: true, once: true});
}
window.addEventListener("hashchange", scheduleNavigation);
window.addEventListener("load", scheduleNavigation);
const navigationResize = new ResizeObserver(scheduleNavigation);
navigationResize.observe(navigationScroller);
for (const child of navigationScroller.children) navigationResize.observe(child);

async function initialize() {
    appState.meta=await api("/api/meta"); const m=appState.meta;
    $("state-filter").innerHTML='<option value="ALL">All customer states</option>'+m.states.map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join("");
    for(const id of ["start-filter","end-filter"]) { $(id).min=m.start; $(id).max=m.end; }
    $("start-filter").value=m.start; $("end-filter").value=m.end;
    $("scenario-filter").innerHTML=m.scenarios.map(s=>`<option value="${esc(s.scenario)}">${num(s.capacity_minutes)} min / ${fixed(s.cost_multiplier)}× review time</option>`).join("");
    $("scenario-filter").value=m.default_scenario;
    const options=m.batches.map(b=>`<option value="${b}">${esc(dateLabel(b))} · 09:00</option>`).join("");
    $("batch-filter").innerHTML='<option value="all">All 28 screening batches</option>'+options; $("custom-batch").innerHTML=options;
    for(const kind of ["excel","powerbi"]) $("download-"+kind).hidden=!m.downloads[kind];
    const [viewReady, planReady] = await Promise.all([loadView(),loadSavedPlan(),api("/api/evidence").then(renderEvidence)]);
    if (!viewReady || !planReady) throw new Error("The initial workspace data could not be loaded.");
}

$("workspace").addEventListener("delivery:ready", () => {
  renderTrend();
  if (initialNavigationPending) {
    initialNavigationPending = false;
    const section = navigationSections.find(section => `#${section.id}` === location.hash);
    section?.scrollIntoView({block: "start", behavior: "instant"});
  }
  scheduleNavigation();
});

$("view-filters").addEventListener("submit",event=>{event.preventDefault();loadView();});
$("reset-filters").addEventListener("click",()=>{if(!appState.meta)return;$("state-filter").value="ALL";$("start-filter").value=appState.meta.start;$("end-filter").value=appState.meta.end;loadView();});
$("trend-count").addEventListener("click",()=>{appState.trend="count";renderTrend();});
$("trend-rate").addEventListener("click",()=>{appState.trend="rate";renderTrend();});
$("scenario-filter").addEventListener("change",loadSavedPlan); $("batch-filter").addEventListener("change",loadSavedPlan);
$("saved-plan-form").addEventListener("submit",event=>event.preventDefault());
$("saved-mode").addEventListener("click",()=>setMode("saved")); $("custom-mode").addEventListener("click",()=>setMode("custom"));
$("custom-plan-form").addEventListener("submit",event=>{event.preventDefault();runCustomPlan();});
scheduleNavigation();
let resizeTimer; new ResizeObserver(()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(renderTrend,120);}).observe($("trend-chart"));
window.DeliveryConnection.start(initialize);
