import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "./sheet";
const mode = vi.hoisted(() => ({ demo: false }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return mode.demo; } }));
afterEach(() => { cleanup(); mode.demo = false; });

it.each([false, true])("scopes the portaled panel and backdrop only in normal mode (demo=%s)", async demo => {
  mode.demo = demo;
  const user = userEvent.setup();
  render(<Sheet><SheetTrigger>Open sheet</SheetTrigger><SheetContent>
    <SheetTitle>Document details</SheetTitle><SheetDescription>Local test details</SheetDescription>
    <a href="/files">Browse files</a>
  </SheetContent></Sheet>);
  const trigger = screen.getByRole("button", { name: "Open sheet" });
  await user.click(trigger);
  const dialog = screen.getByRole("dialog");
  const overlay = document.querySelector('[data-slot="sheet-overlay"]');
  expect(dialog.classList.contains("normal-workspace")).toBe(!demo);
  expect(overlay?.classList.contains("normal-workspace")).toBe(!demo);
  expect(screen.getByRole("link", { name: "Browse files" })).toHaveAttribute("href", "/files");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(trigger).toHaveFocus();
});
