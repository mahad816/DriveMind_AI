// Public demo journey. Needs the app started with NEXT_PUBLIC_DEMO_MODE=true (npm run e2e:app:demo) and the stub.
import { createRequire } from "node:module";
import { chromium, context, stub, shot, APP, STUB } from "./pw.mjs";
const require = createRequire(import.meta.url);
const { default: AxeBuilder } = require("@axe-core/playwright");

const results = []; const ok = (name, cond, extra = "") => results.push(`${cond ? "PASS" : "FAIL"} ${name}${extra ? ` — ${extra}` : ""}`);
const browser = await chromium.launch();
await stub("reset", { scenario: "demo" }); await stub("control", { turnDelayMs: 400 });
const { page } = await context(browser, {});
try {
  await page.goto(`${APP}/`);
  await page.waitForURL(/\/chat$/);
  await page.getByRole("heading", { name: "Ask the sample library." }).waitFor();
  ok("demo: / opens the sample chat without sign-in", !(await page.getByText("Sign in with Google").isVisible().catch(() => false)));
  await shot(page, "demo-1-new");
  await stub("log/clear");
  await page.getByRole("button", { name: "How much of the fieldwork budget is left?" }).click();
  await page.waitForURL(/\/chat\/.+/); await page.locator("button[data-citation]").first().waitFor();
  const first = await (await fetch(`${STUB}/__stub/last-chat`)).json();
  ok("demo: first question sent to POST /chat with an empty history", first?.question === "How much of the fieldwork budget is left?" && Array.isArray(first.history) && first.history.length === 0 && typeof first.conversation_id === "string", JSON.stringify(first));
  await shot(page, "demo-2-answer");
  await page.fill("#composer", "And what did the supervisor say about limitations?"); await page.keyboard.press("Enter");
  await page.locator("button[data-citation]").nth(1).waitFor().catch(() => {});
  await page.waitForFunction(() => document.querySelectorAll("[data-citation]").length >= 2 && !document.body.innerText.includes("Waiting"));
  const second = await (await fetch(`${STUB}/__stub/last-chat`)).json();
  ok("demo: follow-up carries the earlier turn as history", second?.history?.length === 2 && second.history[0].role === "user", JSON.stringify(second?.history?.map(h => h.role)));
  const paths = (await stub("log")).map(e => e.path);
  ok("demo: no sign-in or server-conversation requests", !paths.some(p => p.startsWith("/auth/") || p.startsWith("/conversations")), JSON.stringify([...new Set(paths)]));
  await page.reload(); await page.locator("button[data-citation]").first().waitFor();
  ok("demo: conversation kept in this browser across a reload", (await page.locator("main").innerText()).includes("How much of the fieldwork budget is left?"));
  const conversationRow = page.getByRole("complementary", { name: "Sample conversations" }).getByRole("link", { name: /fieldwork budget/i });
  ok("demo: conversation listed in the side list", await conversationRow.isVisible());
  let a = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  ok("demo: axe on the answered conversation", a.violations.length === 0, a.violations.map(v => `${v.id}: ${v.nodes[0]?.target}`).join("; "));
  await page.getByRole("link", { name: "Sample documents" }).click();
  await page.getByRole("heading", { name: "Sample documents" }).waitFor();
  const docs = page.locator("main ul li button");
  await docs.first().waitFor();
  ok("demo: sample documents listed", (await docs.count()) > 0 && (await docs.count()) <= 7, `count=${await docs.count()}`);
  const textDoc = page.locator("main ul li button", { hasText: /\.md|\.txt/ }).first();
  if (await textDoc.count()) {
    await textDoc.click(); await page.getByRole("dialog").waitFor();
    await page.waitForFunction(() => { const d = document.querySelector('[role="dialog"]'); return !!d && !d.querySelector('[aria-hidden="true"] .animate-pulse') && (d.textContent ?? "").length > 80; });
    ok("demo: a sample document's text opens", ((await page.getByRole("dialog").innerText()) ?? "").length > 80);
    await shot(page, "demo-3-document");
    await page.keyboard.press("Escape"); await page.getByRole("dialog").waitFor({ state: "detached" });
  }
  a = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  ok("demo: axe on sample documents", a.violations.length === 0, a.violations.map(v => `${v.id}: ${v.nodes[0]?.target}`).join("; "));
  await stub("control", { demoReady: false });
  await page.goto(`${APP}/chat`);
  await page.getByText("The sample library is temporarily unavailable.").waitFor();
  ok("demo: unavailable sample library is said plainly and blocks sending", await page.getByText("The sample library isn't available right now.").isVisible());
  await shot(page, "demo-4-unavailable");
} catch (error) {
  ok("demo journey", false, error.message.split("\n")[0]); await shot(page, "FAIL-demo");
}
if (page.problems.length) results.push(`  console: ${page.problems.slice(0, 5).join(" | ")}`);
console.log(results.join("\n"));
process.exitCode = results.some(r => r.startsWith("FAIL")) ? 1 : 0;
await browser.close();
