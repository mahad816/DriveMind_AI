import assert from "node:assert/strict";
import http from "node:http";
import { once } from "node:events";
import test from "node:test";
import { backendTarget, createApiProxy } from "./api-proxy.mjs";

async function fixture(t, handler, options) {
  const backend = http.createServer(handler);
  backend.listen(0, "127.0.0.1");
  await once(backend, "listening");
  const proxy = http.createServer(createApiProxy(
    backendTarget(`http://127.0.0.1:${backend.address().port}`), options,
  ));
  proxy.listen(0, "127.0.0.1");
  await once(proxy, "listening");
  t.after(async () => {
    for (const server of [proxy, backend]) {
      server.closeAllConnections();
      await new Promise((resolve) => server.close(resolve));
    }
  });
  return `http://127.0.0.1:${proxy.address().port}`;
}

test("runtime target rejects embedded secrets and paths without reflecting them", () => {
  for (const value of [undefined, "ftp://backend", "http://user:private@backend", "http://backend/api", "http://backend/?token=private"]) {
    assert.throws(() => backendTarget(value), { message: "BACKEND_URL must be an HTTP(S) origin without credentials" });
  }
  assert.equal(backendTarget("http://backend.railway.internal:8000").hostname, "backend.railway.internal");
});

test("private POST preserves cookie, Origin, CSRF and body without caching", async (t) => {
  const base = await fixture(t, async (req, res) => {
    assert.equal(req.method, "POST");
    assert.equal(req.url, "/api/v1/conversations/opaque/turns");
    assert.equal(req.headers.origin, "https://frontend.example");
    assert.equal(req.headers.cookie, "__Host-drivemind-session=synthetic");
    assert.equal(req.headers["x-csrf-token"], "synthetic-csrf");
    let body = "";
    for await (const chunk of req) body += chunk;
    assert.equal(JSON.parse(body).question, "private question");
    res.writeHead(202, { "content-type": "application/json", "cache-control": "public" });
    res.end('{"status":"RUNNING"}');
  });
  const result = await fetch(`${base}/api/v1/conversations/opaque/turns`, {
    method: "POST", headers: { Origin: "https://frontend.example", Cookie: "__Host-drivemind-session=synthetic", "X-CSRF-Token": "synthetic-csrf", "Content-Type": "application/json" },
    body: JSON.stringify({ question: "private question" }),
  });
  assert.equal(result.status, 202);
  assert.equal(result.headers.get("cache-control"), "private, no-store");
  assert.equal((await result.json()).status, "RUNNING");
});

test("callback preserves multiple host-only secure cookies and redirect", async (t) => {
  const base = await fixture(t, (req, res) => {
    assert.equal(req.url, "/api/v1/auth/session/google/callback?code=fake&state=fake");
    res.writeHead(303, { location: "https://frontend.example/chat", "set-cookie": ["__Host-drivemind-session=fake; Path=/; Secure; HttpOnly; SameSite=Lax", "binding=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax"] });
    res.end();
  });
  const result = await fetch(`${base}/api/v1/auth/session/google/callback?code=fake&state=fake`, { redirect: "manual" });
  assert.equal(result.status, 303);
  assert.equal(result.headers.get("location"), "https://frontend.example/chat");
  assert.equal(result.headers.getSetCookie().length, 2);
  assert.match(result.headers.getSetCookie()[0], /Secure; HttpOnly; SameSite=Lax/);
  assert.doesNotMatch(result.headers.getSetCookie()[0], /Domain=/);
});

for (const status of [401, 403, 404, 409, 503]) {
  test(`backend ${status} remains an error, private and unmodified`, async (t) => {
    const base = await fixture(t, (_req, res) => { res.writeHead(status); res.end('{"detail":"safe"}'); });
    const result = await fetch(`${base}/api/v1/auth/session`);
    assert.equal(result.status, status);
    assert.equal(result.headers.get("cache-control"), "private, no-store");
    assert.equal(await result.text(), '{"detail":"safe"}');
  });
}

test("proxy allows a response beyond Next rewrite's usual short budget", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let complete;
  const reached = new Promise((resolve) => { complete = resolve; });
  let reply;
  const base = await fixture(t, (_req, res) => { reply = res; complete(); });
  const pending = fetch(`${base}/api/v1/conversations/x/turns`, { method: "POST" });
  await reached;
  t.mock.timers.tick(125_000);
  reply.end('{"status":"COMPLETED"}');
  assert.equal((await pending).status, 200);
});

test("absolute budget returns an uncertain safe error even without upstream data", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let entered;
  const reached = new Promise((resolve) => { entered = resolve; });
  const base = await fixture(t, () => entered());
  const pending = fetch(`${base}/api/v1/conversations/x/turns`, { method: "POST" });
  await reached;
  t.mock.timers.tick(180_001);
  const result = await pending;
  assert.equal(result.status, 502);
  assert.match(await result.text(), /reconcile durable request status/);
});

test("browser disconnect closes the upstream HTTP wait", async (t) => {
  let entered;
  const reached = new Promise((resolve) => { entered = resolve; });
  let upstreamClosed;
  const closed = new Promise((resolve) => { upstreamClosed = resolve; });
  const base = await fixture(t, (_req, res) => { res.on("close", upstreamClosed); entered(); });
  const request = http.get(`${base}/api/v1/conversations/x/turns`);
  request.on("error", () => {});
  await reached;
  request.destroy();
  await closed;
  // This proves transport cleanup only, not cancellation of durable model work.
});
