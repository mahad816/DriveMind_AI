import { chromium, context, stub, shot, APP, STUB } from "./pw.mjs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { default: AxeBuilder } = require("@axe-core/playwright");
const browser = await chromium.launch();
const results = []; const ok = (name, cond, extra = "") => { results.push(`${cond ? "PASS" : "FAIL"} ${name}${extra ? ` — ${extra}` : ""}`); };
async function run(name, fn) {
  const { page, ctx } = await context(browser, {});
  try { await fn(page, ctx); } catch (e) { ok(name, false, e.message.split("\n")[0]); await shot(page, `FAIL-${name}`); }
  if (page.problems.length) results.push(`  console[${name}]: ${page.problems.slice(0, 4).join(" | ")}`);
  await ctx.close();
}
const only = process.env.ONLY?.split(",");
const J = (n, f) => (!only || only.includes(n)) && run(n, f);

await J("prepare", async page => {
  await stub("reset", { scenario: "returning" }); await stub("control", { prepDelayMs: 500 });
  await page.goto(`${APP}/files?view=todo&q=Chapter%201`); await page.waitForSelector("tbody [data-row-open]");
  await page.getByRole("checkbox", { name: /^Select Chapter 1/ }).first().click();
  await page.getByRole("searchbox").fill("locked"); await page.waitForURL(/q=locked/);
  await page.getByRole("checkbox", { name: /^Select Conference abstract/ }).click();
  ok("prepare: selection bar counts 2", await page.getByText("2 of 5").isVisible());
  await shot(page, "prep-1-selected");
  await page.getByRole("button", { name: "Review and prepare" }).click(); await page.getByRole("dialog").waitFor();
  await shot(page, "prep-2-review");
  await page.getByRole("dialog").getByRole("button", { name: "Prepare first document" }).click();
  const tray = page.getByRole("complementary", { name: "Document preparation" });
  await tray.waitFor({ timeout: 5000 }); await shot(page, "prep-3-tray-working");
  for (let i = 0; i < 10; i++) {
    const next = tray.getByRole("button", { name: /Prepare next document|Continue/ });
    const stopped = tray.getByText(/stopped on the server/);
    await next.or(stopped).first().waitFor({ timeout: 30000 });
    if (await stopped.isVisible()) break;
    await shot(page, "prep-4-between"); await next.click(); await next.waitFor({ state: "hidden" }).catch(() => {});
  }
  await shot(page, "prep-5-paused");
  const text = await tray.innerText();
  ok("prepare: doc 1 ready; provider failure pauses with an accurate reason", /Ready/.test(text) && /stopped on the server/.test(text), text.replace(/\n/g, " / ").slice(0, 260));
  await tray.getByRole("button", { name: "Stop tracking" }).click(); await page.getByRole("alertdialog").waitFor();
  await shot(page, "prep-6-stop-confirm");
  await page.getByRole("alertdialog").getByRole("button", { name: /Stop tracking/ }).click(); await tray.waitFor({ state: "hidden" });
  ok("prepare: Stop tracking removes the tray", !(await tray.isVisible().catch(() => false)));
  await page.getByRole("button", { name: "Clear filter" }).click().catch(() => page.getByRole("searchbox").fill("")); await page.waitForURL(u => !u.search.includes("q=")); await page.getByRole("button", { name: /^Ready\s*21/ }).waitFor().catch(() => {});
  const ready = await page.getByRole("button", { name: /^Ready/ }).innerText();
  ok("prepare: Ready count went 20 → 21", /21/.test(ready), ready);
});

await J("turn-failures", async page => {
  await stub("reset", { scenario: "returning" });
  await page.goto(`${APP}/chat`); await page.waitForSelector("#composer");
  await stub("control", { turnMode: "fail" });
  await page.fill("#composer", "What does the canopy survey say?"); await page.keyboard.press("Enter");
  await page.waitForURL(/\/chat\/.+/); await page.getByText("DriveMind couldn't answer this time.").waitFor({ timeout: 15000 }); await shot(page, "fail-1-failed");
  const failed = await page.locator("main").innerText();
  ok("failed turn: explains and offers retry", /couldn.t|didn.t|not answered|failed/i.test(failed) && await page.getByRole("button", { name: /Try again|Ask again/ }).first().isVisible(), failed.slice(-240).replace(/\n/g, " / "));
  await stub("control", { turnMode: "quota" });
  await page.fill("#composer", "And the budget?"); await page.keyboard.press("Enter"); await page.getByText(/question limit/).waitFor({ timeout: 15000 });
  await shot(page, "fail-2-quota");
  const quota = await page.locator("main").innerText();
  ok("quota: says limit reached", /limit/i.test(quota), quota.slice(-200).replace(/\n/g, " / "));
  await stub("control", { turnMode: "drop" });
  await page.reload(); await page.getByText("DriveMind couldn't answer this time.").waitFor();
  const log0 = (await stub("log")).length;
  await page.fill("#composer", "Summarise the supervisor feedback"); await page.keyboard.press("Enter"); await page.getByText("DriveMind can't confirm this question was received.").waitFor({ timeout: 15000 });
  await shot(page, "fail-3-unknown");
  const unknown = await page.locator("main").innerText();
  ok("dropped connection: outcome unknown, not auto-resent", /can.t confirm|won.t be sent again/i.test(unknown), unknown.slice(-260).replace(/\n/g, " / "));
  const sendsAfter = (await stub("log")).slice(log0).filter(e => /turns$/.test(e.path ?? e) && (e.method ?? "POST") === "POST").length;
  ok("dropped connection: exactly one POST until the user acts", sendsAfter === 1, `posts=${sendsAfter}`);
});

await J("degraded", async page => {
  await stub("reset", { scenario: "returning" });
  await page.goto(`${APP}/files`); await page.waitForSelector("tbody [data-row-open]");
  await stub("control", { session: "down" });
  await page.evaluate(() => window.dispatchEvent(new Event("focus"))); await page.getByText(/can.t reach its server/).waitFor({ timeout: 10000 });
  await shot(page, "degraded-1");
  ok("degraded: library still visible", await page.locator("tbody [data-row-open]").first().isVisible());
  const banner = await page.getByRole("status").allInnerTexts();
  ok("degraded: banner explains read-only", banner.some(t => /read-only|can.t reach|reconnect|offline/i.test(t)), banner.join(" | ").slice(0, 200));
  await stub("control", { session: "ok" });
  await page.evaluate(() => window.dispatchEvent(new Event("focus"))); await page.getByText(/can.t reach its server/).waitFor({ state: "hidden", timeout: 10000 });
  const after = await page.getByRole("status").allInnerTexts();
  ok("degraded: recovers without reload", !after.some(t => /read-only|can.t reach/i.test(t)));
  await stub("control", { signedIn: false });
  await page.evaluate(() => window.dispatchEvent(new Event("focus"))); await page.getByRole("button", { name: "Sign in with Google" }).waitFor({ timeout: 10000 });
  ok("401: private content hidden", !(await page.locator("tbody [data-row-open]").first().isVisible().catch(() => false)));
  await shot(page, "degraded-2-signedout");
});

await J("palette-keyboard", async page => {
  // State-based waits only: each step waits for the condition it depends on, never a fixed delay.
  const focused = () => page.evaluate(() => { const el = document.activeElement; return { row: !!el?.hasAttribute("data-row-open"), text: (el?.textContent ?? "").slice(0, 60) }; });
  await stub("reset", { scenario: "returning" });
  await page.goto(`${APP}/chat`); await page.waitForSelector("#composer");
  await page.keyboard.press("Tab");
  await page.waitForFunction(() => document.activeElement?.tagName === "A");
  const skip = await page.evaluate(() => document.activeElement?.textContent);
  ok("keyboard: first Tab is the skip link", /skip/i.test(skip ?? ""), skip ?? "");
  await page.locator("body").click({ position: { x: 700, y: 300 } });
  await page.keyboard.press("ControlOrMeta+k");
  const box = page.getByRole("combobox"); await box.waitFor();
  ok("palette: opens on ⌘K", await box.isVisible());
  await box.fill("budget");
  await page.getByRole("option").first().waitFor(); await shot(page, "palette-1");
  await page.keyboard.press("Enter");
  await page.waitForURL(u => /\/chat\/|\/files/.test(u.pathname));
  ok("palette: Enter opens first match", true, page.url());
  await page.goto(`${APP}/files`); await page.waitForSelector("tbody [data-row-open]");
  const rows = page.locator("tbody [data-row-open]");
  await rows.first().focus();
  await page.keyboard.press("ArrowDown");
  await page.waitForFunction(() => document.activeElement === document.querySelectorAll("tbody [data-row-open]")[1]);
  const opener = ((await rows.nth(1).textContent()) ?? "").slice(0, 30);
  await page.keyboard.press(" ");
  await page.getByText("1 of 5").waitFor();
  ok("library keys: ↓ then Space selects row 2", true);
  await page.keyboard.press("Enter");
  await page.getByRole("dialog").waitFor(); await page.waitForURL(/file=/);
  ok("library keys: Enter opens file panel", true);
  await shot(page, "filepanel-1");
  await page.keyboard.press("Escape");
  await page.getByRole("dialog").waitFor({ state: "detached" });
  await page.waitForURL(u => !u.search.includes("file="));
  await page.waitForFunction(() => document.activeElement?.hasAttribute("data-row-open"), null, { timeout: 5000 }).catch(() => {});
  const after = await focused();
  ok("file panel: Escape closes, clears the URL and returns focus to the row that opened it", after.row && after.text.startsWith(opener), `${page.url()} ${JSON.stringify(after)} opener=${JSON.stringify(opener)}`);
  // Reopening the same file after a close must work (dismissal is per file).
  await page.keyboard.press("Enter"); await page.getByRole("dialog").waitFor();
  ok("file panel: the same file opens again after closing", await page.getByRole("dialog").isVisible());
  await page.keyboard.press("Escape"); await page.getByRole("dialog").waitFor({ state: "detached" });
});

await J("tab-switch", async page => {
  // Simulates leaving and returning to the tab: both visibilityState and hidden, as browsers set them.
  const leave = () => page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    Object.defineProperty(document, "hidden", { value: true, configurable: true });
    document.dispatchEvent(new Event("visibilitychange")); window.dispatchEvent(new Event("blur"));
  });
  const back = () => page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
    document.dispatchEvent(new Event("visibilitychange")); window.dispatchEvent(new Event("focus"));
  });
  // Every session request is stamped with the phase it was issued in; "flush" lets any handler that reacts to an event
  // issue its request (handlers fetch synchronously or in a microtask), so nothing is attributed to the wrong phase.
  let phase = "setup"; const issued = [];
  page.on("request", r => { if (new URL(r.url()).pathname === "/api/v1/auth/session") issued.push(phase); });
  const flush = () => page.evaluate(() => new Promise(r => requestAnimationFrame(() => setTimeout(r, 0))));
  await stub("reset", { scenario: "returning" });
  // Chat: an unsent draft and the composer element itself survive.
  await page.goto(`${APP}/chat`); await page.waitForSelector("#composer");
  await page.fill("#composer", "half-written question about canopy cover");
  const composer = await page.$("#composer");
  const perReturn = []; let onLeave = 0;
  for (let i = 0; i < 3; i++) {
    phase = `leave${i}`; await leave(); await flush();
    phase = `back${i}`;
    const answered = page.waitForResponse(r => new URL(r.url()).pathname === "/api/v1/auth/session", { timeout: 5000 }).catch(() => null);
    await back(); await answered; await flush();
    onLeave += issued.filter(p => p === `leave${i}`).length; perReturn.push(issued.filter(p => p === `back${i}`).length);
  }
  ok("tab switch: at most one session check per return, none on leaving", perReturn.every(n => n <= 1) && onLeave === 0, `per return=${JSON.stringify(perReturn)}, on leave=${onLeave}`);
  ok("tab switch: draft kept, composer not remounted", await composer.evaluate(el => el.isConnected && el.value) === "half-written question about canopy cover");
  // Library: selection and the open file panel survive, with no extra file-list fetch for fresh data.
  await page.goto(`${APP}/files?view=todo`); await page.waitForSelector("tbody [data-row-open]");
  await page.getByRole("checkbox", { name: /^Select / }).first().click();
  await page.locator("tbody [data-row-open]").nth(1).click(); await page.getByRole("dialog").waitFor();
  const panelTitle = await page.getByRole("dialog").getByRole("heading").first().innerText();
  await flush(); await stub("log/clear");
  for (let i = 0; i < 3; i++) {
    await leave(); await flush();
    const answered = page.waitForResponse(r => new URL(r.url()).pathname === "/api/v1/auth/session", { timeout: 5000 }).catch(() => null);
    await back(); await answered; await flush();
  }
  const paths = (await stub("log")).map(e => e.path ?? e);
  ok("tab switch: selection kept", await page.getByText("1 of 5").isVisible());
  ok("tab switch: file panel still open on the same file", await page.getByRole("dialog").isVisible() && (await page.getByRole("dialog").getByRole("heading").first().innerText()) === panelTitle);
  ok("tab switch: no file-list refetch while data is fresh, no skeleton", paths.filter(p => p === "/files").length === 0 && await page.locator("tbody [data-row-open]").first().isVisible(), JSON.stringify(paths));
});

await J("ask-link", async page => {
  // Old builds auto-sent "?ask=" links. The rebuilt chat must never send a question the person did not submit.
  await stub("reset", { scenario: "returning" });
  await stub("log/clear");
  await page.goto(`${APP}/chat?ask=${encodeURIComponent("Private question from a link")}`); await page.waitForSelector("#composer");
  // The ready count appears only after the workspace has loaded everything it loads on arrival.
  await page.getByText(/documents? (is|are) ready/).first().waitFor();
  await page.evaluate(() => new Promise(r => requestAnimationFrame(() => setTimeout(r, 0))));
  const posts = (await stub("log")).filter(e => e.method === "POST").map(e => e.path);
  ok("?ask= link sends nothing", posts.length === 0, JSON.stringify(posts));
});

await J("send-and-cite", async page => {
  await stub("reset", { scenario: "returning" });
  await page.goto(`${APP}/chat`); await page.waitForSelector("#composer");
  await stub("log/clear");
  await page.fill("#composer", "How much of the fieldwork budget is left?");
  // Enter and a click on Send in the same moment must produce one conversation and one question.
  await Promise.all([page.keyboard.press("Enter"), page.getByRole("button", { name: /^Send/ }).click({ force: true }).catch(() => {})]);
  await page.waitForURL(/\/chat\/.+/); await page.waitForSelector("button[data-citation]", { timeout: 15000 });
  const posts = (await stub("log")).filter(e => e.method === "POST").map(e => e.path);
  ok("duplicate Enter + click: one create, one question", posts.filter(p => p === "/conversations").length === 1 && posts.filter(p => /\/turns(\/stream)?$/.test(p)).length === 1, JSON.stringify(posts));
  const files = (await (await fetch(`${STUB}/files`)).json()).files;
  const hrefs = await page.locator('a[href*="drive.google.com"]').evaluateAll(as => as.map(a => a.getAttribute("href")));
  const internal = new Set(files.map(f => f.id)), google = new Set(files.map(f => f.drive_file_id));
  ok("citation Drive links use Google's file id, never DriveMind's internal id",
    hrefs.length > 0 && hrefs.every(h => [...google].some(g => h.includes(g)) && ![...internal].some(i => h.includes(i))), JSON.stringify(hrefs));
  await page.getByRole("button", { name: "Ask again", exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll('aside[aria-label="Sources for this answer"]').length === 2);
  const folds = page.getByRole("button", { name: /^Sources ·/ });
  ok("polish: Ask again sends one new turn and folds the old sources", (await stub("log")).filter(e => e.method === "POST" && /\/turns$/.test(e.path)).length === 2 && await folds.first().getAttribute("aria-expanded") === "false" && await folds.last().getAttribute("aria-expanded") === "true");
  await page.locator("button[data-citation]").first().click();
  ok("polish: following an old citation reopens its sources", await folds.first().getAttribute("aria-expanded") === "true");
  await page.locator("#composer").blur();
  await page.keyboard.press("?");
  await page.getByRole("dialog", { name: "Keyboard shortcuts" }).waitFor();
  ok("polish: keyboard shortcut opens help", await page.getByText("Send the question", { exact: true }).isVisible());
  await page.keyboard.press("Escape");

});

await J("axe", async (page) => {
  const pages = ["/chat", "/files", "/settings", "/welcome?guide=1"];
  for (const theme of ["light", "dark"]) {
    await stub("reset", { scenario: "returning" });
    await page.emulateMedia({ colorScheme: theme }); await page.evaluate(t => localStorage.setItem("theme", t), theme).catch(() => {});
    for (const p of pages) {
      await page.goto(`${APP}${p}`); await page.locator("main h1").first().waitFor();
      const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
      ok(`axe ${theme} ${p}`, r.violations.length === 0, r.violations.map(v => `${v.id}(${v.nodes.length}): ${v.nodes[0]?.target}`).join("; "));
    }
    const id = (await (await fetch(`${STUB}/conversations?limit=1`)).json()).conversations[0].id;
    await page.goto(`${APP}/chat/${id}`); await page.waitForSelector("button[data-citation]");
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    ok(`axe ${theme} conversation`, r.violations.length === 0, r.violations.map(v => `${v.id}(${v.nodes.length}): ${v.nodes[0]?.target}`).join("; "));
  }
  await stub("reset", { scenario: "new" }); await page.goto(`${APP}/chat`); await page.waitForSelector("text=Sign in with Google");
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  ok("axe sign-in", r.violations.length === 0, r.violations.map(v => `${v.id}: ${v.nodes[0]?.target}`).join("; "));
});

await J("onboarding", async page => {
  await stub("reset", { scenario: "new" }); await stub("control", { connectAfterOAuth: true });
  await page.goto(`${APP}/`); await page.getByRole("button", { name: "Sign in with Google" }).click();
  await page.waitForURL(/\/welcome/, { timeout: 15000 }); await page.getByRole("button", { name: "Connect Google Drive" }).waitFor(); await shot(page, "onb-1-welcome");
  ok("onboarding: login lands on /welcome", /\/welcome/.test(page.url()), page.url());
  await page.getByRole("button", { name: "Connect Google Drive" }).click();
  await page.waitForURL(/\/welcome/, { timeout: 15000 }); await page.getByText(/read-only access|Reading file names|files found|No files found/).first().waitFor({ timeout: 15000 }); await shot(page, "onb-2-connected");
  const t = await page.locator("main").innerText();
  ok("onboarding: Drive step done after connect", /read-only access|Reading file names|files found|No files found/i.test(t), t.slice(0, 300).replace(/\n/g, " / "));
  await page.getByRole("link", { name: "Choose documents" }).waitFor({ timeout: 20000 }); await shot(page, "onb-3-found");
  ok("onboarding: Choose documents offered", await page.getByRole("link", { name: "Choose documents" }).isVisible());
});

await new Promise(r => setTimeout(r, 100));
console.log(results.join("\n")); process.exitCode = results.some(r => r.startsWith("FAIL")) ? 1 : 0;
await browser.close();
