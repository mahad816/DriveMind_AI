// Synthetic DriveMind backend for UI development and Playwright journeys.
// Loopback only, fictional data, no Google, no OpenAI, no database. Implements the /api/v1 contract the frontend's
// strict parsers expect (lib/api/*). Control endpoints under /api/v1/__stub/ switch scenarios and failure modes.
import http from "node:http";
import { randomUUID } from "node:crypto";
import { corpus, answerFor } from "./corpus.mjs";

const PORT = Number(process.env.STUB_PORT ?? 8100);
const FRONTEND = process.env.STUB_FRONTEND ?? "http://localhost:3100";
const OWNER = "5f0c1d2e-3a4b-4c5d-8e6f-7a8b9c0d1e2f";
const OTHER_OWNER = "9e8d7c6b-5a49-4382-a1b0-c9d8e7f6a5b4";
const CSRF = "synthetic-csrf-token";
const iso = (ms = Date.now()) => new Date(ms).toISOString();
const sleep = ms => new Promise(r => setTimeout(r, ms));

let s; // whole mutable state
function fileRow(f, i, status) {
  const id = `00000000-0000-4000-8000-${String(i + 1).padStart(12, "0")}`;
  return { id, user_id: OWNER, drive_file_id: `synthDrive${String(i + 1).padStart(5, "0")}`, name: f.name, mime_type: f.mime,
    folder_path: f.folder, modified_at: f.modified, indexed_at: status === "indexed" ? f.modified : null, status,
    created_at: "2026-09-01T09:00:00Z", updated_at: f.modified };
}
function seedConversations() {
  const day = 86_400_000, now = Date.now();
  const make = (title, ageMs, questions) => {
    const id = randomUUID(), created = now - ageMs;
    const turns = questions.map((q, n) => completedTurn(q, n + 1, created + n * 60_000));
    s.conversations.set(id, { id, title, title_is_manual: false, created_at: iso(created), updated_at: iso(created + turns.length * 60_000),
      last_activity_at: iso(created + turns.length * 60_000), metadata_version: 1, content_version: turns.length, turns });
  };
  make("Gaps in the methods chapter", 2 * 3600_000, ["What does the methods chapter still need before submission?"]);
  make("Canopy cover versus surface temperature", 5 * 3600_000, ["How strong is the link between canopy cover and surface temperature in the survey data?", "Which districts are outliers?"]);
  make("Fieldwork budget remaining", 3 * day, ["How much of the fieldwork budget is left?"]);
  make("Supervisor feedback from October", 6 * day, ["Summarise the October supervisor feedback."]);
  for (let i = 0; i < 34; i++) make(`Reading notes, week ${34 - i}`, (12 + i * 2) * day, ["What were the key points from this week's reading?"]);
}
function reset(scenario = "returning") {
  s = { scenario, signedIn: scenario !== "new", owner: OWNER, connected: scenario !== "new" && scenario !== "disconnected-new",
    session: "ok", turnMode: "ok", turnDelayMs: 1400, streamDelayMs: 90, filesDown: false, sourceGone: false, statusDown: false,
    prepDelayMs: 1200, syncDelayMs: 3500, dropNextPrep: false, files: [], jobs: new Map(), latest: null, conversations: new Map(),
    requests: [], requestLog: [], connectAfterOAuth: true };
  if (scenario === "returning") {
    s.files = corpus.files.map((f, i) => fileRow(f, i, f.status));
    seedConversations();
  } else if (scenario === "demo") {
    // Public demo runtime: no sign-in, a small fixed sample library, every resource route served anonymously.
    s.signedIn = false; s.connected = false; s.demoReady = true; s.lastChat = null;
    s.files = corpus.files.filter(f => f.status === "indexed").slice(0, 7).map((f, i) => fileRow(f, i, "indexed"));
  } else if (scenario === "empty-library") {
    s.files = [];
  } else if (scenario === "nothing-ready") {
    s.files = corpus.files.map((f, i) => fileRow(f, i, f.status === "indexed" ? "discovered" : f.status));
  }
}
reset();

// ---------- DTO helpers (exact key sets: the frontend rejects anything else) ----------
const meta = c => ({ id: c.id, title: c.title, title_is_manual: c.title_is_manual, created_at: c.created_at, updated_at: c.updated_at,
  last_activity_at: c.last_activity_at, metadata_version: c.metadata_version, content_version: c.content_version });
function completedTurn(question, sequence, atMs = Date.now()) {
  const { answer, citations } = answerFor(question, s.files);
  return { id: randomUUID(), client_request_id: randomUUID(), sequence, question, operation: "ASK", source_turn_id: null,
    created_at: iso(atMs), updated_at: iso(atMs + 4000), retrieval_count: citations.length + 3, status: "COMPLETED",
    finished_at: iso(atMs + 4000), error_code: null, query_id: randomUUID(), answer, citations };
}
const stored = t => { const { _expiresAt, ...rest } = t; void _expiresAt; return rest; };
const withStatus = t => ({ ...stored(t), execution_expired: t.status === "RUNNING" && !!t._expiresAt && Date.now() > t._expiresAt });

// ---------- HTTP plumbing ----------
const send = (res, code, body, headers = {}) => {
  res.writeHead(code, { "Content-Type": "application/json", ...headers });
  res.end(body === undefined ? "" : JSON.stringify(body));
};
const needCsrf = (req, res) => {
  if (req.headers["x-csrf-token"] !== CSRF) { send(res, 403, { detail: "Application session request could not be verified." }); return false; }
  return true;
};
const unauth = res => send(res, 401, { detail: "Your application session is invalid or expired." });

function settle(job) {
  if (!job || job.status !== "running") return job;
  const elapsed = Date.now() - job._t;
  if (job.operation === "SYNC") {
    const pending = s._syncPending ?? [];
    const share = Math.min(1, elapsed / s.syncDelayMs), target = Math.floor(pending.length * share);
    while (s._syncAdded < target) { s.files.push(pending[s._syncAdded]); s._syncAdded++; }
    job.processed = s._syncAdded; job.total = pending.length; job.updated_at = iso();
    if (share >= 1) Object.assign(job, { status: "completed", succeeded: s._syncAdded, completed_at: iso() });
    return job;
  }
  if (elapsed < s.prepDelayMs) return job;
  const file = s.files.find(f => f.id === job.file_id);
  const outcome = job.operation === "INGEST" ? corpus.prepOutcome(file.name) : "ok";
  Object.assign(job, { processed: 1, completed_at: iso(), updated_at: iso() });
  if (outcome === "document" || outcome === "provider") {
    Object.assign(job, { status: "failed", failed: 1, failure_class: outcome, error: "1 of 1 files failed during ingestion." });
    file.status = "failed";
  } else if (outcome === "skip") {
    Object.assign(job, { status: "completed", skipped: 1 }); file.status = "skipped";
  } else {
    Object.assign(job, { status: "completed", succeeded: 1 });
    file.status = job.operation === "BUILD" ? "indexed" : "indexing";
    if (job.operation === "BUILD") file.indexed_at = iso();
  }
  file.updated_at = iso();
  return job;
}
const jobView = job => job && Object.fromEntries(Object.entries(settle(job)).filter(([k]) => !k.startsWith("_")));
function newJob(operation, fileId = null) {
  const job = { id: randomUUID(), user_id: s.owner, status: "running", operation, file_id: fileId, full_sync: false, recovery_required: false,
    total: operation === "SYNC" ? 0 : 1, processed: 0, succeeded: 0, failed: 0, skipped: 0, failure_class: null, started_at: iso(),
    completed_at: null, error: null, created_at: iso(), updated_at: iso(), _t: Date.now() };
  s.jobs.set(job.id, job); s.latest = job;
  return job;
}

async function runTurn(c, turn) {
  // Simulated generation; the turn row is RUNNING meanwhile.
  await sleep(s.turnDelayMs);
  if (turn.status !== "RUNNING") return;
  if (s.turnMode === "fail") Object.assign(turn, { status: "FAILED", error_code: "TURN_FAILED", finished_at: iso(), updated_at: iso() });
  else if (s.turnMode === "running") { turn._expiresAt = Date.now() + 4000; return; }
  else {
    const done = completedTurn(turn.question, turn.sequence);
    Object.assign(turn, { status: "COMPLETED", finished_at: iso(), updated_at: iso(), error_code: null, query_id: done.query_id,
      answer: done.answer, citations: done.citations, retrieval_count: done.retrieval_count });
  }
  c.content_version += 1; c.updated_at = iso(); c.last_activity_at = iso();
}

function routeConversations(req, res, p, url, body) {
  const parts = p.split("/").filter(Boolean); // conversations, id, turns, turnId, interrupt|stream
  if (parts.length === 1) {
    if (req.method === "POST") {
      if (!needCsrf(req, res)) return;
      const existing = [...s.conversations.values()].find(c => c._req === body.create_request_id);
      if (existing) return send(res, 200, meta(existing));
      const id = randomUUID(), now = iso();
      const c = { id, title: "New conversation", title_is_manual: false, created_at: now, updated_at: now, last_activity_at: now,
        metadata_version: 1, content_version: 0, turns: [], _req: body.create_request_id };
      s.conversations.set(id, c);
      return send(res, 201, meta(c));
    }
    const limit = Number(url.searchParams.get("limit") ?? 30), cursor = Number(url.searchParams.get("cursor") ?? 0);
    const rows = [...s.conversations.values()].sort((a, b) => b.last_activity_at.localeCompare(a.last_activity_at));
    const page = rows.slice(cursor, cursor + limit);
    return send(res, 200, { conversations: page.map(meta), next_cursor: cursor + limit < rows.length ? String(cursor + limit) : null });
  }
  const c = s.conversations.get(parts[1]);
  if (!c) return send(res, 404, { detail: "Conversation not found." });
  if (parts.length === 2) {
    if (req.method === "GET") {
      const limit = Number(url.searchParams.get("limit") ?? 50), before = url.searchParams.get("before_sequence");
      const eligible = c.turns.filter(t => before === null || t.sequence < Number(before));
      const page = eligible.slice(-limit);
      return send(res, 200, { conversation: meta(c), turns: page.map(stored),
        next_before_sequence: eligible.length > limit ? page[0].sequence : null });
    }
    if (!needCsrf(req, res)) return;
    if (body.expected_metadata_version !== c.metadata_version) return send(res, 409, { detail: "Conversation metadata version is stale." });
    if (req.method === "PATCH") {
      Object.assign(c, { title: body.title.trim(), title_is_manual: true, metadata_version: c.metadata_version + 1, updated_at: iso() });
      return send(res, 200, meta(c));
    }
    if (req.method === "DELETE") { s.conversations.delete(c.id); res.writeHead(204); return res.end(); }
  }
  if (parts[2] === "turns" && parts.length === 3 || parts[3] === "stream") {
    if (!needCsrf(req, res)) return;
    const stream = parts[3] === "stream";
    const replay = c.turns.find(t => t.client_request_id === body.client_request_id);
    if (replay) {
      const code = replay.status === "RUNNING" ? 202 : 200;
      if (stream) return sse(res, [["receipt", { http_status: code, receipt: { turn: withStatus(replay), replayed: true } }]]);
      return send(res, code, { turn: withStatus(replay), replayed: true });
    }
    if (s.turnMode === "quota") return send(res, 429, { detail: "The hourly question limit was reached. Please try again later." }, { "Retry-After": "900" });
    if (body.expected_content_version !== c.content_version) return send(res, 409, { detail: "Conversation content changed." });
    if (s.turnMode === "drop") { s.turnMode = "ok"; return req.socket.destroy(); }
    const sequence = (c.turns.at(-1)?.sequence ?? 0) + 1, now = iso();
    const turn = { id: randomUUID(), client_request_id: body.client_request_id, sequence, question: body.question.trim(), operation: "ASK",
      source_turn_id: null, created_at: now, updated_at: now, retrieval_count: 0, status: "RUNNING", finished_at: null, error_code: null,
      query_id: null, answer: null, citations: [] };
    c.turns.push(turn);
    if (c.turns.length === 1 && !c.title_is_manual) { c.title = titleFrom(turn.question); }
    c.last_activity_at = now;
    const work = runTurn(c, turn);
    if (stream) return streamTurn(res, c, turn, work);
    if (s.turnMode === "running") return send(res, 202, { turn: withStatus(turn), replayed: true });
    return work.then(() => {
      if (turn.status === "COMPLETED") send(res, 200, { turn: withStatus(turn), replayed: false });
      else send(res, 503, { turn: withStatus(turn), replayed: false });
    });
  }
  if (parts[2] === "turns" && parts.length >= 4) {
    const turn = c.turns.find(t => t.id === parts[3]);
    if (!turn) return send(res, 404, { detail: "Turn not found." });
    if (parts[4] === "interrupt") {
      if (!needCsrf(req, res)) return;
      if (turn.status === "RUNNING") Object.assign(turn, { status: "INTERRUPTED", error_code: "TURN_INTERRUPTED", finished_at: iso(), updated_at: iso(), _expiresAt: undefined });
      c.content_version += 1;
      return send(res, 200, withStatus(turn));
    }
    return send(res, 200, withStatus(turn));
  }
  send(res, 404, { detail: "Not found" });
}
const titleFrom = q => { const t = q.replace(/\s+/g, " ").replace(/[?.!]+$/, ""); return t.length > 52 ? `${t.slice(0, 50).trimEnd()}…` : t; };
function sse(res, events) {
  res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
  for (const [name, data] of events) res.write(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`);
  res.end();
}
async function streamTurn(res, c, turn, work) {
  res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
  const write = (name, data) => res.write(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`);
  write("accepted", { turn: withStatus(turn), replayed: false });
  write("state", { phase: "searching" });
  const preview = answerFor(turn.question, s.files).answer.replace(/\[\d+\]/g, "");
  await sleep(500);
  const words = preview.split(/(\s+)/);
  let text = "";
  for (let i = 0; i < words.length && i < 160; i += 6) { text += words.slice(i, i + 6).join(""); write("provisional", { text }); await sleep(s.streamDelayMs); }
  write("state", { phase: "validating" });
  await work;
  if (turn.status === "COMPLETED") write("complete", { http_status: 200, receipt: { turn: withStatus(turn), replayed: false } });
  else write("error", { code: "TURN_FAILED", message: "The answer could not be produced.", receipt: { turn: withStatus(turn), replayed: false } });
  res.end();
}

http.createServer((req, res) => {
  const url = new URL(req.url, "http://stub"), p = url.pathname.replace(/^\/api\/v1/, "");
  let raw = "";
  req.on("data", chunk => { raw += chunk; });
  req.on("end", async () => {
    const body = raw ? (() => { try { return JSON.parse(raw); } catch { return {}; } })() : {};
    if (!p.startsWith("/__stub")) s.requestLog.push({ t: Date.now(), method: req.method, path: p });
    // ---- control ----
    if (p === "/__stub/reset") { reset(body.scenario ?? url.searchParams.get("scenario") ?? "returning"); return send(res, 200, { ok: true, scenario: s.scenario }); }
    if (p === "/__stub/control") { for (const k of Object.keys(body)) if (k in s && !["files", "jobs", "conversations"].includes(k)) s[k] = body[k]; return send(res, 200, { ok: true }); }
    if (p === "/__stub/log") return send(res, 200, s.requestLog);
    if (p === "/__stub/last-chat") return send(res, 200, s.lastChat ?? null);
    if (p === "/__stub/log/clear") { s.requestLog = []; return send(res, 200, { ok: true }); }
    if (p === "/__stub/switch-account") { s.owner = OTHER_OWNER; s.files = []; s.conversations = new Map(); return send(res, 200, { ok: true }); }
    if (p === "/__stub/oauth") {
      // Stands in for accounts.google.com: completes the intent, then the backend's fixed redirect.
      const intent = url.searchParams.get("intent");
      if (intent === "LOGIN") s.signedIn = true;
      if (intent === "CONNECT_DRIVE" && s.connectAfterOAuth) s.connected = true;
      res.writeHead(302, { Location: `${FRONTEND}/settings?login=success` });
      return res.end();
    }
    // ---- session ----
    if (s.session === "hang" && p.startsWith("/auth/session")) { await sleep(20_000); return send(res, 503, { detail: "Unavailable" }); }
    if (s.session === "down" && req.method === "GET" && p === "/auth/session") return send(res, 503, { detail: "Service unavailable" });
    if (p === "/auth/session" && req.method === "GET") {
      return s.signedIn ? send(res, 200, { kind: "GOOGLE_ACCOUNT", user_id: s.owner, csrf_token: CSRF }) : unauth(res);
    }
    if (p === "/auth/session/google" && req.method === "POST") {
      if (req.headers["x-drivemind-auth"] !== "1") return send(res, 403, { detail: "Forbidden" });
      if (body.intent === "CONNECT_DRIVE" && !needCsrf(req, res)) return;
      return send(res, 200, { authorization_url: `https://accounts.google.com/o/oauth2/v2/auth?synthetic=1&intent=${body.intent}` });
    }
    if (p === "/auth/session/logout" && req.method === "POST") { if (!needCsrf(req, res)) return; s.signedIn = false; res.writeHead(204); return res.end(); }
    if (p === "/health") return send(res, 200, { status: "ok" });
    if (s.scenario === "demo") {
      if (p === "/index/status") return send(res, 200, { connected: false, job: null, demo_mode: true, demo_ready: s.demoReady,
        corpus_version: "synthetic-1", demo_questions: ["How much of the fieldwork budget is left?", "What did the supervisor say about limitations?"] });
      if (p === "/chat" && req.method === "POST") {
        s.lastChat = body;
        await sleep(s.turnDelayMs);
        if (s.turnMode === "fail") return send(res, 503, { detail: "The sample library is temporarily unavailable." });
        const { answer, citations } = answerFor(body.question ?? "", s.files);
        return send(res, 200, { query_id: randomUUID(), user_id: OWNER, answer, citations, retrieval_count: citations.length + 3, message: "ok" });
      }
      if (!["/files", "/index/pending"].includes(p) && !/^\/(files\/[^/]+\/content|sources\/[^/]+)$/.test(p)) return send(res, 403, { detail: "This operation is unavailable in public demo mode." });
    } else if (!s.signedIn) return unauth(res);
    // ---- private routes ----
    if (p === "/index/status") {
      if (s.statusDown) return send(res, 503, { detail: "Synthetic outage" });
      const id = url.searchParams.get("job_id");
      return send(res, 200, { connected: s.connected, demo_mode: false, job: id ? jobView(s.jobs.get(id)) ?? null : jobView(s.latest) });
    }
    if (p === "/index/pending") return send(res, 200, { to_ingest: 0, to_chunk: 0, to_build: 0, any_pending: false });
    if (p === "/files") {
      if (s.filesDown) return send(res, 503, { detail: "Synthetic outage" });
      // Like the real backend, file status and job completion are one state: settle any active job first.
      if (s.latest && ["queued", "running"].includes(s.latest.status)) settle(s.latest);
      return send(res, 200, { files: s.files, total: s.files.length });
    }
    const content = /^\/files\/([^/]+)\/content$/.exec(p);
    if (content) {
      const file = s.files.find(f => f.id === content[1]);
      if (!file) return send(res, 404, { detail: "File not found" });
      if (!file.mime_type.startsWith("text/")) return send(res, 415, { detail: "Unsupported" });
      res.writeHead(200, { "Content-Type": file.mime_type });
      return res.end(corpus.textFor(file.name));
    }
    const source = /^\/sources\/([^/]+)$/.exec(p);
    if (source) {
      const chunk = corpus.chunks.find(c => c.chunk_id === source[1]);
      if (!chunk || s.sourceGone) return send(res, 404, { detail: "Source not found" });
      const file = s.files.find(f => f.name === chunk.file);
      return send(res, 200, { chunk_id: chunk.chunk_id, drive_file_id: file?.id ?? chunk.chunk_id, filename: chunk.file,
        mime_type: file?.mime_type ?? "application/vnd.google-apps.document", chunk_index: chunk.index, text: chunk.text,
        modified_at: file?.modified_at ?? "2026-10-01T10:00:00Z" });
    }
    if (p === "/index/sync" && req.method === "POST") {
      if (!needCsrf(req, res)) return;
      if (!s.connected) return send(res, 503, { detail: "Google Drive is not connected." });
      if (s.latest && settle(s.latest).status === "running") return send(res, 409, { detail: "An unresolved indexing job already exists for this account." });
      const job = newJob("SYNC");
      const known = new Set(s.files.map(f => f.name));
      s._syncPending = corpus.files.map((f, i) => fileRow(f, i, "discovered")).filter(f => !known.has(f.name));
      s._syncAdded = 0;
      return send(res, 202, { job_id: job.id, status: "queued", message: "Accepted" });
    }
    const stage = { "/index/ingest": "INGEST", "/index/chunk": "CHUNK", "/index/build": "BUILD" }[p];
    if (stage && req.method === "POST") {
      if (!needCsrf(req, res)) return;
      const fileId = url.searchParams.get("file_id"), file = s.files.find(f => f.id === fileId);
      if (!file) return send(res, 404, { detail: "Synced file not found" });
      if (!s.connected) return send(res, 503, { detail: "Google Drive is not connected." });
      if (s.latest && settle(s.latest).status === "running") return send(res, 409, { detail: "An unresolved indexing job already exists for this account." });
      const job = newJob(stage, fileId); file.status = "indexing";
      if (s.dropNextPrep) { s.dropNextPrep = false; return req.socket.destroy(); }
      return send(res, 202, { job_id: job.id, status: "queued", message: "Accepted" });
    }
    if (p.startsWith("/conversations")) return routeConversations(req, res, p, url, body);
    send(res, 404, { detail: "Not found" });
  });
}).listen(PORT, "127.0.0.1", () => console.log(`synthetic backend on 127.0.0.1:${PORT}`));
