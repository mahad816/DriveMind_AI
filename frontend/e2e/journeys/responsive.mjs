import { chromium, context, stub, shot, APP, STUB } from "./pw.mjs";
const browser = await chromium.launch();
const widths = (process.env.WIDTHS ?? "1100,820,390,320").split(",").map(Number);
const themes = (process.env.THEMES ?? "light,dark").split(",");
const overflow = [];
for (const theme of themes) for (const width of widths) {
  await stub("reset", { scenario: "returning" });
  const mobile = width < 768;
  const { page, ctx } = await context(browser, { width, height: mobile ? 844 : 900, theme, mobile });
  const check = async name => {
    const o = await page.evaluate(() => ({ doc: document.documentElement.scrollWidth - innerWidth, body: document.body.scrollWidth - innerWidth }));
    if (o.doc > 0 || o.body > 0) overflow.push(`${theme} ${width} ${name}: +${Math.max(o.doc, o.body)}px`);
    await shot(page, `${theme}-${width}-${name}`);
  };
  await page.goto(`${APP}/chat`); await page.waitForSelector("#composer"); await page.waitForTimeout(900); await check("newchat");
  const id = (await (await fetch(`${STUB}/conversations?limit=2`)).json()).conversations[0].id;
  await page.goto(`${APP}/chat/${id}`); await page.waitForSelector("button[data-citation]"); await page.waitForTimeout(600); await check("conversation");
  if (width < 1280) { await page.locator("button[data-citation='1']").first().click(); await page.waitForTimeout(700); await check("sources-sheet"); await page.keyboard.press("Escape"); await page.waitForTimeout(300); }
  await page.goto(`${APP}/files`); await page.waitForSelector("table tbody tr td button"); await page.waitForTimeout(500); await check("library");
  await page.goto(`${APP}/settings`); await page.waitForTimeout(700); await check("settings");
  if (mobile) { await page.goto(`${APP}/chat`); await page.waitForTimeout(500); await page.getByRole("button", { name: "Open navigation" }).click(); await page.waitForTimeout(500); await check("drawer"); }
  if (page.problems.length) console.log(theme, width, page.problems.join("\n"));
  await ctx.close();
}
// Signed-out screen
for (const width of [1440, 390]) {
  await stub("reset", { scenario: "new" });
  const { page, ctx } = await context(browser, { width, height: width < 768 ? 844 : 900 });
  await page.goto(`${APP}/chat`); await page.waitForSelector("text=Sign in with Google"); await page.waitForTimeout(900);
  await shot(page, `signin-${width}`); await ctx.close();
}
console.log(overflow.length ? `OVERFLOW:\n${overflow.join("\n")}` : "no horizontal overflow");
process.exitCode = overflow.length ? 1 : 0;
await browser.close();
