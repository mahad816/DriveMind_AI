import http from "node:http";
import https from "node:https";

// Deployment-only transport. It never verifies identity or changes backend auth.
const hopHeaders = new Set([
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
  "te", "trailer", "transfer-encoding", "upgrade",
]);

function endToEndHeaders(headers) {
  const excluded = new Set(hopHeaders);
  for (const name of String(headers.connection ?? "").split(",")) {
    excluded.add(name.trim().toLowerCase());
  }
  return Object.fromEntries(Object.entries(headers).filter(([name]) => !excluded.has(name)));
}

export function backendTarget(value) {
  try {
    const target = new URL(value);
    if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password
        || target.pathname !== '/' || target.search || target.hash) throw new Error();
    return target;
  } catch {
    // Never include URLs or credentials in diagnostics.
    throw new Error("BACKEND_URL must be an HTTP(S) origin without credentials");
  }
}

export function createApiProxy(target, { timeoutMs = 180_000 } = {}) {
  const transport = target.protocol === "https:" ? https : http;
  return (request, response) => {
    const upstream = transport.request({
      protocol: target.protocol, hostname: target.hostname, port: target.port,
      // Preserve the raw path/query, but never let it choose another destination.
      path: request.url, method: request.method,
      headers: { ...endToEndHeaders(request.headers), host: target.host },
    });
    const timer = setTimeout(() => upstream.destroy(), timeoutMs);
    const fail = () => {
      if (!response.headersSent) {
        response.writeHead(502, { "content-type": "application/json", "cache-control": "private, no-store" });
        response.end('{"detail":"API response unavailable; reconcile durable request status."}');
      } else response.destroy();
    };
    upstream.on("error", fail);
    upstream.on("response", (incoming) => {
      response.writeHead(incoming.statusCode ?? 502, {
        ...endToEndHeaders(incoming.headers), "cache-control": "private, no-store",
      });
      incoming.on("error", () => response.destroy());
      incoming.pipe(response);
    });
    const finish = () => { clearTimeout(timer); upstream.destroy(); };
    response.on("close", finish);
    request.on("aborted", finish);
    request.on("error", finish);
    request.pipe(upstream);
  };
}
