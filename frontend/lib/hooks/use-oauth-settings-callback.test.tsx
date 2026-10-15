import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useOAuthSettingsCallback } from "./use-oauth-settings-callback";
const test = vi.hoisted(() => ({ replace: vi.fn(), refresh: vi.fn(), pushToast: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: test.replace }), useSearchParams: () => test.params }));
vi.mock("@/components/providers/application-session-provider", () => ({ useApplicationSession: () => ({ refresh: test.refresh }) }));
vi.mock("@/components/ui/toast-provider", () => ({ useToast: () => ({ pushToast: test.pushToast }) }));
beforeEach(() => { vi.clearAllMocks(); test.refresh.mockResolvedValue(true); });
afterEach(cleanup);
it("routes a verified successful callback through authoritative home readiness", async () => {
  test.params = new URLSearchParams("login=success&email=untrusted"); renderHook(useOAuthSettingsCallback);
  await waitFor(() => expect(test.replace).toHaveBeenCalledWith("/")); expect(test.refresh).toHaveBeenCalledOnce();
});
it("does not navigate into setup on an unverified callback", async () => {
  test.params = new URLSearchParams("login=success"); test.refresh.mockResolvedValue(false); renderHook(useOAuthSettingsCallback);
  await waitFor(() => expect(test.replace).toHaveBeenCalledWith("/settings")); expect(test.pushToast).not.toHaveBeenCalled();
});
it("ignores arbitrary profile hints as identity evidence", async () => {
  test.params = new URLSearchParams("email=untrusted&connected=true"); renderHook(useOAuthSettingsCallback);
  await waitFor(() => expect(test.replace).toHaveBeenCalledWith("/settings")); expect(test.pushToast).not.toHaveBeenCalled();
});
it("does nothing for an ordinary Settings visit", () => {
  test.params = new URLSearchParams(); renderHook(useOAuthSettingsCallback); expect(test.refresh).not.toHaveBeenCalled();
});
