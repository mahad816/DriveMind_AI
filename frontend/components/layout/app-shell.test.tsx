import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AppShell } from "./app-shell";
const state = vi.hoisted(() => ({ demo: false, path: "/files" }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return state.demo; } }));
vi.mock("next/navigation", () => ({ usePathname: () => state.path }));
vi.mock("./conversation-sidebar", () => ({ ConversationSidebar: ({ collapsible }: { collapsible: boolean }) => <nav data-collapsible={String(collapsible)}>Sidebar</nav> }));
vi.mock("./mobile-header", () => ({ MobileHeader: () => <header>Mobile navigation</header> }));
vi.mock("./connection-banner", () => ({ ConnectionBanner: () => <p>Connection banner</p> }));
vi.mock("@/components/onboarding/onboarding-gate", () => ({ OnboardingGate: ({ children }: { children: React.ReactNode }) => children }));
afterEach(() => { cleanup(); state.demo = false; });
it.each(["/files", "/prepare"])("%s keeps its own contextual connection guidance", path => {
  state.path = path; render(<AppShell><p>Page content</p></AppShell>);
  expect(screen.queryByText("Connection banner")).toBeNull(); expect(screen.getByText("Page content")).toBeInTheDocument();
});
it("preserves connection guidance elsewhere", () => {
  state.path = "/settings"; render(<AppShell><p>Settings</p></AppShell>); expect(screen.getByText("Connection banner")).toBeInTheDocument();
});
it("keeps HarborDesk Files chrome unchanged", () => {
  state.path = "/files"; state.demo = true; render(<AppShell><p>Samples</p></AppShell>); expect(screen.getByText("Connection banner")).toBeInTheDocument();
});

it.each([false, true])("desktop collapse is enabled only for normal mode (demo=%s)", demo => {
  state.path = "/files"; state.demo = demo; render(<AppShell><p>Page content</p></AppShell>);
  expect(screen.getByRole("navigation")).toHaveAttribute("data-collapsible", String(!demo));
});
