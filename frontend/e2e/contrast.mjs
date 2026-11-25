// Measures WCAG 2.2 contrast for every token pair used as text or as an essential UI boundary, in both themes.
// Reads the tokens straight from app/globals.css so the check cannot drift from the shipped palette.
// Usage: node e2e/contrast.mjs  (exit code 1 when any pair fails)
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const block = selector => {
  const start = css.indexOf(`${selector} {`), body = css.slice(start, css.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/--([a-z-]+):\s*([^;]+);/g)].map(m => [m[1], m[2].trim()]));
};
const themes = { light: block(":root"), dark: { ...block(":root"), ...block(".dark") } };
function parse(value) {
  const hex = /^#([0-9a-f]{6})$/i.exec(value);
  if (hex) return [0, 2, 4].map(i => parseInt(hex[1].slice(i, i + 2), 16)).concat(1);
  const rgb = /^rgb\((\d+) (\d+) (\d+) \/ ([\d.]+)\)$/.exec(value);
  if (rgb) return [+rgb[1], +rgb[2], +rgb[3], +rgb[4]];
  throw new Error(`Unparsed colour ${value}`);
}
const over = (top, base) => top.slice(0, 3).map((c, i) => c * top[3] + base[i] * (1 - top[3])).concat(1);
const lum = ([r, g, b]) => [r, g, b].map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
  .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };

const text = ["ink", "graphite", "faint", "archive-text", "caution", "fault"];
const surfaces = ["paper", "sheet", "well"];
let failed = 0;
for (const [theme, t] of Object.entries(themes)) {
  const c = name => parse(t[name]);
  const checks = [];
  for (const fg of text) for (const bg of surfaces) checks.push([`${fg} on ${bg}`, c(fg), c(bg), 4.5]);
  // Washes are translucent: composite them over the surface they sit on.
  checks.push(["ink on highlight (sheet)", c("ink"), over(c("highlight"), c("sheet")), 4.5]);
  checks.push(["ink on highlight (paper)", c("ink"), over(c("highlight"), c("paper")), 4.5]);
  checks.push(["archive-text on archive-wash (sheet)", c("archive-text"), over(c("archive-wash"), c("sheet")), 4.5]);
  checks.push(["caution on caution-wash (sheet)", c("caution"), over(c("caution-wash"), c("sheet")), 4.5]);
  checks.push(["fault on fault-wash (sheet)", c("fault"), over(c("fault-wash"), c("sheet")), 4.5]);
  checks.push(["archive-ink on archive (primary button)", c("archive-ink"), c("archive"), 4.5]);
  // Non-text: control edges and the focus ring must reach 3:1 against what they sit on (1.4.11).
  for (const bg of ["paper", "sheet"]) {
    checks.push([`edge (control edge) on ${bg}`, c("edge"), c(bg), 3]);
    checks.push([`archive (focus ring) on ${bg}`, c("archive"), c(bg), 3]);
  }
  for (const [name, fg, bg, min] of checks) {
    const value = ratio(fg, bg), ok = value >= min;
    if (!ok) failed++;
    console.log(`${ok ? "pass" : "FAIL"}  ${theme.padEnd(5)}  ${value.toFixed(2).padStart(5)} ≥ ${min}  ${name}`);
  }
}
console.log(failed ? `\n${failed} pair(s) below the WCAG threshold` : "\nAll pairs meet WCAG 2.2 AA");
process.exit(failed ? 1 : 0);
