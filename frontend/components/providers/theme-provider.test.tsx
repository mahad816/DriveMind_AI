import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ThemeProvider } from "./theme-provider";

// The operating system is dark in every case below: only the stored choice may change the outcome.
function stubMatchMedia(prefersDark: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("dark") ? prefersDark : false, media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  }));
}
let store: Map<string, string>;
beforeEach(() => {
  store = new Map(); document.documentElement.className = ""; stubMatchMedia(true);
  Object.defineProperty(window, "localStorage", { configurable: true, value: {
    getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); }, removeItem: (k: string) => { store.delete(k); }, clear: () => store.clear(),
  } });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); document.documentElement.className = ""; });

it("defaults to Light when the user has no saved preference, even on a dark system", async () => {
  render(<ThemeProvider><p>app</p></ThemeProvider>);
  await waitFor(() => expect(document.documentElement.classList.contains("light")).toBe(true));
  expect(document.documentElement.classList.contains("dark")).toBe(false);
});
it("keeps an existing saved Dark choice", async () => {
  window.localStorage.setItem("theme", "dark");
  render(<ThemeProvider><p>app</p></ThemeProvider>);
  await waitFor(() => expect(document.documentElement.classList.contains("dark")).toBe(true));
});
it("keeps an existing saved System choice and follows the system", async () => {
  window.localStorage.setItem("theme", "system");
  render(<ThemeProvider><p>app</p></ThemeProvider>);
  await waitFor(() => expect(document.documentElement.classList.contains("dark")).toBe(true));
});
it("keeps an existing saved Light choice", async () => {
  window.localStorage.setItem("theme", "light");
  render(<ThemeProvider><p>app</p></ThemeProvider>);
  await waitFor(() => expect(document.documentElement.classList.contains("light")).toBe(true));
});
