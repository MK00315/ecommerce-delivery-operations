"use strict";

// This transport also runs under Node's test runner without a browser or network.
(function () {
  async function requestJSON(path, options = {}) {
    const {timeoutMs = 20000, startupSignal, ...fetchOptions} = options;
    const controller = new AbortController();
    const signals = [fetchOptions.signal, startupSignal].filter(Boolean);
    const abort = () => controller.abort();
    for (const signal of signals) {
      if (signal.aborted) controller.abort();
      else signal.addEventListener("abort", abort, {once: true});
    }
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
    try {
      const response = await fetch(path, {...fetchOptions, signal: controller.signal, cache: "no-store",
        headers: {Accept: "application/json", ...fetchOptions.headers}});
      if (!(response.headers.get("content-type") || "").includes("application/json")) {
        throw new Error("The analysis server is still starting. Please try again shortly.");
      }
      const body = await response.json();
      if (!response.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Check the selected values, then try again.");
      }
      return body;
    } catch (error) {
      if (timedOut) throw new Error("The server is taking longer than expected. Please try again.");
      throw error;
    } finally {
      clearTimeout(timer);
      for (const signal of signals) signal.removeEventListener("abort", abort);
    }
  }

  function delay(milliseconds, signal) {
    return new Promise((resolve, reject) => {
      const abort = () => { clearTimeout(timer); reject(new DOMException("Cancelled", "AbortError")); };
      const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, milliseconds);
      if (signal.aborted) abort(); else signal.addEventListener("abort", abort, {once: true});
    });
  }

  function createConnection({request = requestJSON, online = () => navigator.onLine,
    wait = delay, now = () => performance.now(), deadlineMs = 180000, onStage = () => {}} = {}) {
    let controller = null, generation = 0, phase = "idle", loadWorkspace = null, deadlineAt = 0;
    const notify = (stage, details = {}) => { phase = stage; onStage(stage, details); };
    return {
      get signal() { return controller?.signal; },
      get remainingMs() { return controller ? Math.max(1, deadlineAt - now()) : null; },
      get phase() { return phase; },
      stop() { ++generation; controller?.abort(); controller = null; },
      offline() {
        if (["ready", "idle"].includes(phase)) return;
        this.stop(); notify("offline");
      },
      async start(load = loadWorkspace) {
        if (!load) throw new Error("A workspace loader is required.");
        loadWorkspace = load;
        this.stop(); const token = generation;
        controller = new AbortController(); const signal = controller.signal;
        const startedAt = now(), deadline = startedAt + deadlineMs;
        deadlineAt = deadline;
        let attempt = 0, serverReady = false;
        notify("connecting", {startedAt});
        while (now() < deadline && token === generation) {
          if (!online()) { this.offline(); return false; }
          try {
            const health = await request("/api/health", {signal, timeoutMs: Math.min(15000, deadline - now())});
            if (health.status !== "ready" || health.application !== "delivery-ops" || health.source_orders !== 99441) {
              throw new Error("The workspace service has not reported readiness.");
            }
            if (signal.aborted || token !== generation) return false;
            serverReady = true; notify("preparing", {startedAt});
            // The UI remains covered until all required initial data has loaded.
            await load(signal);
            if (signal.aborted || token !== generation) return false;
            controller = null; notify("ready", {startedAt}); return true;
          } catch (error) {
            if (signal.aborted || token !== generation) return false;
            if (!online()) { this.offline(); return false; }
            const remaining = deadline - now();
            if (remaining <= 0) break;
            notify(serverReady ? "preparing" : "connecting", {startedAt, retrying: true});
            try { await wait(Math.min(remaining, [1500, 2500, 4000, 6000][Math.min(attempt++, 3)]), signal); }
            catch (_) { return false; }
          }
        }
        if (token === generation) { controller = null; notify("error", {startedAt, serverReady}); }
        return false;
      }
    };
  }

  if (typeof module !== "undefined" && module.exports) { module.exports = {requestJSON, createConnection}; return; }

  const element = id => document.getElementById(id);
  let clock = null, started = 0;
  function updateClock() {
    const seconds = Math.max(0, Math.floor((performance.now() - started) / 1000));
    element("connection-elapsed").textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
    if (seconds >= 20 && connection.phase === "connecting") {
      element("connection-description").textContent = "The analysis server is taking a little longer to respond. We are still trying to connect.";
    }
  }

  function renderStage(stage, details) {
    const screen = element("connection-screen"), workspace = element("workspace");
    clearInterval(clock); screen.dataset.state = stage;
    const waiting = stage === "connecting" || stage === "preparing";
    const serverReady = stage === "preparing" || stage === "ready" || details.serverReady;
    screen.setAttribute("aria-busy", String(waiting));
    element("connection-server-step").className = `connection-step ${serverReady ? "completed" : waiting ? "current" : "failed"}`;
    element("connection-workspace-step").className = `connection-step ${stage === "ready" ? "completed" : stage === "preparing" ? "current" : "pending"}`;
    element("connection-server-icon").textContent = serverReady ? "✓" : "2";
    element("connection-workspace-icon").textContent = stage === "ready" ? "✓" : "3";
    element("connection-server-step").querySelector("h3").textContent = serverReady ? "Server connected" : "Connecting to server";
    for (const step of document.querySelectorAll(".connection-step")) {
      const state = step.classList.contains("completed") ? "complete" : step.classList.contains("current") ? "in progress" : step.classList.contains("failed") ? "not connected" : "waiting";
      step.setAttribute("aria-label", `${step.querySelector("h3").textContent}: ${state}`);
    }
    element("connection-retry").hidden = waiting || stage === "ready";
    const copy = {
      connecting: ["Connecting to Delivery Ops", "The dashboard is ready. We are connecting to the analysis server."],
      preparing: ["Preparing your workspace", "The server is connected. We are loading charts and review scenarios."],
      offline: ["No connection detected", "Reconnect to the internet, then try again. Your dashboard will be here."],
      error: [serverReady ? "The workspace could not be loaded" : "The connection is taking longer", "We could not finish connecting this time. Try again in a moment."],
      ready: ["Your workspace is ready", "Opening Delivery Ops."]
    }[stage];
    element("connection-status").textContent = copy[0]; element("connection-description").textContent = copy[1];
    if (details.startedAt !== undefined) { started = details.startedAt; updateClock(); }
    if (waiting) clock = setInterval(updateClock, 1000);
    if (stage === "ready") {
      workspace.hidden = false;
      workspace.dispatchEvent(new CustomEvent("delivery:ready"));
      const restoreFocus = screen.contains(document.activeElement);
      screen.classList.add("connection-leaving");
      setTimeout(() => {
        screen.hidden = true;
        if (restoreFocus) { const heading = workspace.querySelector("h1"); heading.tabIndex = -1; heading.focus({preventScroll: true}); }
      }, matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 240);
    } else {
      screen.hidden = false; screen.classList.remove("connection-leaving");
    }
  }

  const connection = createConnection({onStage: renderStage});
  window.DeliveryConnection = {
    start: load => connection.start(load),
    request: (path, options = {}) => requestJSON(path, {...options, startupSignal: connection.signal,
      timeoutMs: Math.min(options.timeoutMs || 20000, connection.remainingMs || 20000)})
  };
  element("connection-retry").addEventListener("click", () => connection.start());
  window.addEventListener("offline", () => connection.offline());
  window.addEventListener("online", () => { if (connection.phase === "offline") connection.start(); });
})();
