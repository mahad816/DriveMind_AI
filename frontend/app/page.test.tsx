import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import HomePage from "@/app/page";
import { DemoHomeRedirect } from "@/components/onboarding/demo-home-redirect";
const mode = vi.hoisted(() => ({ demo: false }));
const router = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return mode.demo; } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/components/onboarding/onboarding-gate", () => ({ OnboardingAwareHomeRedirect: () => <div>Normal onboarding</div> }));
afterEach(() => { mode.demo = false; vi.clearAllMocks(); window.history.replaceState({}, "", "/"); });
describe("homepage entry", () => {
  it("keeps the demo root statically renderable and mounts its redirect", () => {
    mode.demo = true;
    expect(HomePage().type).toBe(DemoHomeRedirect);
  });
  it("redirects to chat while preserving query parameters", async () => {
    mode.demo = true;
    window.history.replaceState({}, "", "/?ask=Explain%20notes&tag=a&tag=b");
    render(<DemoHomeRedirect />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/chat?ask=Explain%20notes&tag=a&tag=b"));
  });
  it("redirects a plain demo root to chat", async () => {
    mode.demo = true;
    render(<DemoHomeRedirect />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/chat"));
  });
  it("retains normal-mode knowledge/onboarding routing", () => {
    render(HomePage());
    expect(screen.getByText("Normal onboarding")).toBeInTheDocument();
  });
});
