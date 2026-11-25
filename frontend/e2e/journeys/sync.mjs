// Synthetic transport faults with the real Marginalia controls and discovery controller.
import { chromium, context, stub, APP } from "./pw.mjs";
import assert from "node:assert/strict";
const browser = await chromium.launch();
try {
  await stub("reset", { scenario: "returning" });
  const { ctx, page } = await context(browser);
  let available = false, connected = true, mode = "reject", posts = 0;
  await ctx.route("**/api/v1/index/status*", route => route.fulfill({ json: { connected, sync_available: available, job: null } }));
  await ctx.route("**/api/v1/index/sync*", route => {
    posts++;
    return route.fulfill({ status: 503, json: { detail: mode === "reject" ? "Indexing execution is unavailable until its worker and recovery support are ready." : "Unknown transport outcome" } });
  });
  await page.goto(`${APP}/files`);
  await page.getByText("Sync is temporarily unavailable. Please try again.", { exact: true }).waitFor();
  assert.equal(posts, 0);
  available = true;
  await page.getByRole("button", { name: "Check sync status", exact: true }).first().click();
  await page.getByRole("button", { name: "Check Drive for changes", exact: true }).click();
  await page.getByText("Sync is temporarily unavailable. Please try again.", { exact: true }).waitFor();
  assert.equal(posts, 1);
  await page.reload();
  await page.getByRole("button", { name: "Check Drive for changes", exact: true }).waitFor();
  mode = "unknown";
  await page.getByRole("button", { name: "Check Drive for changes", exact: true }).click();
  await page.getByText(/request could not be confirmed/).waitFor();
  await page.getByRole("button", { name: "Check sync status", exact: true }).first().click();
  await page.reload();
  await page.getByText(/request could not be confirmed/).waitFor();
  assert.equal(posts, 2, "unknown request was not resubmitted after check/reload");
  // Session revalidation on tab return is a read; it cannot retry the unknown sync.
  await page.evaluate(() => { document.dispatchEvent(new Event("visibilitychange")); window.dispatchEvent(new Event("focus")); });
  await page.getByRole("button", { name: "Check sync status", exact: true }).first().click();
  assert.equal(posts, 2);
  await ctx.close();
  const fresh = await context(browser);
  connected = false;
  await fresh.ctx.route("**/api/v1/index/status*", route => route.fulfill({ json: { connected, sync_available: null, job: null } }));
  await fresh.page.goto(`${APP}/files`);
  await fresh.page.getByText("Your Google Drive connection needs to be renewed.", { exact: true }).waitFor();
  assert.equal(await fresh.page.getByRole("button", { name: "Check Drive for changes", exact: true }).count(), 0);
  await fresh.ctx.close();
  console.log("PASS sync: unavailable, availability recovery, definite rejection, refresh, unknown outcome, tab return and disconnected state");
} finally { await browser.close(); }
