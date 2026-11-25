// Shared helper: isolated headless Chromium (fresh profile per context), console and network capture.
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
const require = createRequire(import.meta.url);
export const { chromium } = require("@playwright/test");
export const APP = "http://127.0.0.1:3100", STUB = "http://127.0.0.1:8100/api/v1";
// Screenshots go outside the repository unless SHOTS says otherwise.
export const SHOTS = process.env.SHOTS ?? join(tmpdir(), "drivemind-e2e-shots");
mkdirSync(SHOTS, { recursive: true });
export async function stub(path, body) {
  const r = await fetch(`${STUB}/__stub/${path}`, { method: "POST", body: JSON.stringify(body ?? {}) });
  return r.json();
}
export async function context(browser, { width = 1440, height = 900, theme = "light", mobile = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: theme, isMobile: mobile, hasTouch: mobile, deviceScaleFactor: 1 });
  await ctx.addInitScript(t => { try { if (!localStorage.getItem("theme")) localStorage.setItem("theme", t); } catch {} }, theme);
  // Stand-in for accounts.google.com: never leaves the machine.
  await ctx.route("https://accounts.google.com/**", route => {
    const intent = new URL(route.request().url()).searchParams.get("intent");
    return route.fulfill({ status: 302, headers: { Location: `${STUB}/__stub/oauth?intent=${intent}` } });
  });
  const page = await ctx.newPage();
  page.problems = [];
  page.on("console", m => { if (["error", "warning"].includes(m.type())) page.problems.push(`${m.type()}: ${m.text().slice(0, 300)}`); });
  page.on("pageerror", e => page.problems.push(`pageerror: ${e.message.slice(0, 300)}`));
  page.on("response", r => { if (r.status() >= 500 && r.url().includes("/api/")) page.problems.push(`http ${r.status()} ${r.url()}`); });
  return { ctx, page };
}
export const shot = (page, name) => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });
