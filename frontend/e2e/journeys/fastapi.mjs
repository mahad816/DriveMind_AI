// Opt-in companion to tests/security/test_integrated_frontend_browser.py.
// Real session, inventory, conversation and source routes; only the RAG/Drive providers are synthetic.
import { chromium, APP } from "./pw.mjs";
import assert from "node:assert/strict";
const browser = await chromium.launch();
try {
  const ctx = await browser.newContext();
  const paths = [];
  await ctx.route("**/api/v1/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    paths.push(`${request.method()} ${url.pathname}`);
    const headers = { ...request.headers(), cookie: process.env.E2E_FASTAPI_COOKIE, origin: process.env.E2E_FASTAPI_ORIGIN };
    delete headers.host; delete headers["content-length"];
    const response = await fetch(`${process.env.E2E_FASTAPI}${url.pathname}${url.search}`, { method: request.method(), headers, body: request.postData() ?? undefined });
    await route.fulfill({ status: response.status, headers: Object.fromEntries(response.headers), body: Buffer.from(await response.arrayBuffer()) });
  });
  const page = await ctx.newPage();
  await page.goto(`${APP}/files`);
  await page.getByText("Integration.txt", { exact: true }).first().waitFor();
  await page.getByText("Sync is temporarily unavailable. Please try again.", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Check sync status", exact: true }).first().click();
  assert(!paths.some(p => p === "POST /api/v1/index/sync"));
  await page.goto(`${APP}/chat`);
  await page.locator("#composer").fill("What does the integration document say?");
  await page.locator("#composer").press("Enter");
  await page.waitForURL(/\/chat\/.+/);
  await page.getByText("Synthetic integrated answer", { exact: false }).waitFor();
  await page.locator("button[data-citation]").first().click();
  await page.getByText("Synthetic integrated evidence.", { exact: true }).first().waitFor();
  const id = page.url();
  await page.reload();
  await page.getByText("Synthetic integrated answer", { exact: false }).waitFor();
  assert.equal(page.url(), id);
  assert.equal(paths.filter(p => /^POST .*\/turns$/.test(p)).length, 1);
  assert(paths.some(p => /^GET .*\/sources\//.test(p)));
  console.log("PASS real FastAPI: session, inventory, sync availability, conversation, persisted history, answer and source");
} finally { await browser.close(); }
