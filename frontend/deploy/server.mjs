import http from "node:http";
import next from "next";
import { backendTarget, createApiProxy } from "./api-proxy.mjs";

const port = Number(process.env.PORT ?? 3000);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid PORT");
const proxy = createApiProxy(backendTarget(process.env.BACKEND_URL));
const app = next({ dev: false, hostname: "::", port });
await app.prepare();
const handle = app.getRequestHandler();
let stopping = false;
const server = http.createServer((request, response) => {
  if (stopping) {
    response.writeHead(503, { "cache-control": "no-store" });
    response.end();
  } else if (request.url === "/_deployment/health") {
    response.writeHead(200, { "content-type": "application/json", "cache-control": "no-store" });
    response.end('{"status":"ok"}');
  } else if (request.url?.startsWith("/api/v1/") || request.url === "/api/v1") {
    proxy(request, response);
  } else {
    void handle(request, response).catch(() => {
      if (!response.headersSent) response.writeHead(500, { "cache-control": "no-store" });
      response.end();
    });
  }
});
server.requestTimeout = 180_000;
server.listen(port, "::");
function shutdown() {
  if (stopping) return;
  stopping = true;
  // Stop new requests and retain active proxy ownership during drain.
  const deadline = setTimeout(() => {
    server.closeAllConnections();
  }, 185_000);
  deadline.unref();
  server.close(async () => {
    clearTimeout(deadline);
    await app.close();
  });
  server.closeIdleConnections();
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
