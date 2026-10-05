import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });

describe("demo chat errors", () => {
  it.each([
    [413, "private payload detail", "Your message is too large for the public demo. Please shorten it and try again."],
    [422, "Question exceeds the demo character limit", "Your message is too long. Please keep it under 4,000 characters."],
    [429, "private rate detail", "The public demo is busy right now. Please try again shortly."],
    [500, "private provider detail", "Something went wrong while answering. Please try again."],
    [503, "private database detail", "The sample knowledge base is temporarily unavailable. Please try again shortly."],
  ])("maps status %s without exposing backend detail", async (status, detail, expected) => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    const { chatErrorMessage, ApiError: ErrorType } = await import("@/lib/api/errors");
    expect(chatErrorMessage(new ErrorType(status, detail))).toBe(expected);
  });

  it("preserves normal-mode useful errors", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "false");
    const { chatErrorMessage, ApiError: ErrorType } = await import("@/lib/api/errors");
    expect(chatErrorMessage(new ErrorType(422, "Validation detail"))).toBe("Validation detail");
    expect(chatErrorMessage(new Error("Network unavailable"))).toBe("Network unavailable");
    expect(new ErrorType(429, "detail").status).toBe(429);
  });
});
