import { describe, expect, it } from "vitest";
import { syncView } from "./drive-sync";
import type { DiscoveryState } from "@/lib/knowledge/discovery";
const state = (over: Partial<DiscoveryState> = {}): DiscoveryState => ({ phase: "idle", job: null, message: "", connected: true, syncAvailable: null, ...over });
describe("Marginalia sync controls", () => {
  it("accepts absent availability as unknown, while an explicit false offers a read-only status check", () => {
    expect(syncView(state(), true).canStart).toBe(true);
    expect(syncView(state({ syncAvailable: false }), true)).toMatchObject({ canStart: false, needsCheck: true });
    expect(syncView(state({ phase: "unavailable" }), true).needsCheck).toBe(true);
  });
  it.each(["unknown", "blocked"] as const)("keeps %s outcomes visible and never offers a resubmission", phase => {
    expect(syncView(state({ phase, message: "Review this exact job" }), true)).toMatchObject({ canStart: false, needsCheck: true, line: "Review this exact job" });
  });
  it("does not turn session expiry into a misleading connect message", () => {
    expect(syncView(state({ phase: "blocked", connected: false, message: "Your session expired. Sign in again." }), true).line).toContain("session expired");
  });
  it("disables mutations while disconnected, running, or read-only", () => {
    expect(syncView(state({ connected: false }), true).canStart).toBe(false);
    expect(syncView(state({ phase: "active" }), true)).toMatchObject({ canStart: false, running: true });
    expect(syncView(state(), false).canStart).toBe(false);
  });
  it("distinguishes connected but undiscovered files from ready inventory", () => {
    expect(syncView(state(), true, { total: 0, indexed: 0 }).line).toContain("Sync to find your files");
    expect(syncView(state(), true, { total: 3, indexed: 1 }).line).toContain("1 file is ready");
  });
});
