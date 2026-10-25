const {test} = require("node:test");
const assert = require("node:assert/strict");
const {requestJSON, createConnection} = require("../dashboard/assets/connection.js");
const healthy = {status: "ready", application: "delivery-ops", source_orders: 99441};

function fixture(request, settings = {}) {
  let time = 0;
  const stages = [], delays = [];
  const connection = createConnection({request, online: () => true, now: () => time,
    wait: async ms => { delays.push(ms); time += ms; }, deadlineMs: 12000,
    onStage: stage => stages.push(stage), ...settings});
  return {connection, stages, delays};
}

test("a warm server opens only after initial workspace data is ready", async () => {
  const {connection, stages} = fixture(async () => healthy);
  let loaded = 0;
  assert.equal(await connection.start(async signal => { assert.equal(signal.aborted, false); loaded++; }), true);
  assert.equal(loaded, 1);
  assert.deepEqual(stages, ["connecting", "preparing", "ready"]);
  assert.equal(connection.signal, undefined);
});

test("a Render HTML loading response is retried rather than accepted as data", async t => {
  t.mock.method(globalThis, "fetch", async () => new Response("<html>Starting service</html>", {headers: {"content-type": "text/html"}}));
  await assert.rejects(requestJSON("/api/health"), /still starting/);
});

test("API validation messages remain readable after startup", async t => {
  t.mock.method(globalThis, "fetch", async () => Response.json({detail: "Choose a customer state"}, {status: 422}));
  await assert.rejects(requestJSON("/api/view?state=ZZ"), /Choose a customer state/);
});

test("a stalled request is aborted and reports a useful timeout", async t => {
  t.mock.method(globalThis, "fetch", async (_path, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new DOMException("Cancelled", "AbortError")), {once: true});
  }));
  await assert.rejects(requestJSON("/api/health", {timeoutMs: 10}), /taking longer than expected/);
});

test("a caller cancellation remains an abort rather than a timeout", async t => {
  t.mock.method(globalThis, "fetch", async (_path, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new DOMException("Cancelled", "AbortError")), {once: true});
  }));
  const controller = new AbortController();
  const result = requestJSON("/api/view", {signal: controller.signal});
  controller.abort();
  await assert.rejects(result, {name: "AbortError"});
});

test("cold-start failures wait with bounded backoff and then recover", async () => {
  let requests = 0, loads = 0;
  const {connection, delays, stages} = fixture(async () => {
    if (++requests < 3) throw new Error("Starting");
    return healthy;
  });
  assert.equal(await connection.start(async () => { loads++; }), true);
  assert.deepEqual(delays, [1500, 2500]);
  assert.equal(loads, 1);
  assert.equal(stages.at(-1), "ready");
});

test("unavailable servers reach an honest error and stop polling", async () => {
  let calls = 0;
  const {connection, delays, stages} = fixture(async () => { calls++; throw new Error("Unavailable"); });
  assert.equal(await connection.start(async () => assert.fail("Must not load data")), false);
  assert.equal(delays.reduce((a, b) => a + b, 0), 12000);
  assert.equal(calls, 4);
  assert.equal(stages.at(-1), "error");
});

test("a different JSON service cannot falsely unlock the workspace", async () => {
  const {connection, stages} = fixture(async () => ({...healthy, application: "another-service"}));
  assert.equal(await connection.start(async () => assert.fail("Wrong service")), false);
  assert.equal(stages.includes("ready"), false);
});

test("offline startup makes no requests and can be retried after reconnecting", async () => {
  let online = false, calls = 0;
  const {connection, stages} = fixture(async () => { calls++; return healthy; }, {online: () => online});
  assert.equal(await connection.start(async () => {}), false);
  assert.equal(calls, 0);
  assert.equal(stages.at(-1), "offline");
  online = true;
  assert.equal(await connection.start(), true);
  assert.equal(calls, 1);
});

test("failed initial data keeps the dashboard covered until a complete retry", async () => {
  let loads = 0;
  const {connection, stages} = fixture(async () => healthy);
  assert.equal(await connection.start(async () => {
    if (++loads === 1) throw new Error("Scenario request failed");
  }), true);
  assert.equal(loads, 2);
  assert.equal(stages.filter(stage => stage === "ready").length, 1);
});

test("a second attempt cancels an old connection and ignores stale responses", async () => {
  let release, calls = 0, loaded = 0;
  const old = new Promise(resolve => { release = resolve; });
  const {connection, stages} = fixture(async () => ++calls === 1 ? old : healthy);
  const first = connection.start(async () => { loaded++; });
  const second = connection.start();
  assert.equal(await second, true);
  release(healthy);
  assert.equal(await first, false);
  assert.equal(loaded, 1);
  assert.equal(stages.filter(stage => stage === "ready").length, 1);
});

test("going offline cancels startup without allowing a late ready response", async () => {
  let release;
  const response = new Promise(resolve => { release = resolve; });
  const {connection, stages} = fixture(async () => response);
  const starting = connection.start(async () => assert.fail("Cancelled load"));
  connection.offline(); release(healthy);
  assert.equal(await starting, false);
  assert.equal(stages.at(-1), "offline");
});

test("requests preserve JSON POST settings and explicitly avoid caching", async t => {
  let seen;
  t.mock.method(globalThis, "fetch", async (path, options) => {
    seen = {path, options}; return Response.json({saved: false});
  });
  assert.deepEqual(await requestJSON("/api/planning/custom", {method: "POST", body: "{}", headers: {"Content-Type": "application/json"}}), {saved: false});
  assert.equal(seen.options.method, "POST");
  assert.equal(seen.options.body, "{}");
  assert.equal(seen.options.cache, "no-store");
  assert.equal(seen.options.headers.Accept, "application/json");
});
