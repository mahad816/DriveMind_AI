import { afterEach, describe, expect, it, vi } from "vitest";
import HomePage from "@/app/page";
const mode = vi.hoisted(() => ({ demo: false }));
const redirect = vi.hoisted(() => vi.fn((path: string) => { throw new Error(`REDIRECT:${path}`); }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return mode.demo; } }));
vi.mock("next/navigation", () => ({ redirect }));
vi.mock("@/components/onboarding/onboarding-gate", () => ({ OnboardingAwareHomeRedirect: () => null }));
afterEach(() => { mode.demo = false; vi.clearAllMocks(); });
describe("homepage entry", () => {
  it("redirects demo entry on the server without mounting a client status gate", async () => {
    mode.demo = true; await expect(HomePage({})).rejects.toThrow("REDIRECT:/chat");
  });
  it("preserves ask and repeated query parameters on demo entry", async () => {
    mode.demo = true;
    await expect(HomePage({ searchParams: Promise.resolve({ ask: "Explain notes", tag: ["a", "b"] }) })).rejects.toThrow("REDIRECT:/chat?ask=Explain+notes&tag=a&tag=b");
  });
  it("retains normal-mode knowledge/onboarding routing", async () => {
    const page = await HomePage({}); expect(page.type).toBeDefined(); expect(redirect).not.toHaveBeenCalled();
  });
});
