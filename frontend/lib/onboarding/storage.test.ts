import { describe, expect, it, beforeEach, vi } from "vitest";

import {
  consumeOnboardingOAuthPending,
  hasCompletedOnboarding,
  markOnboardingComplete,
  setOnboardingOAuthPending,
} from "@/lib/onboarding/storage";

describe("onboarding storage", () => {
  beforeEach(() => {
    const store: Record<string, string> = {};
    vi.stubGlobal("window", {
      localStorage: {
        getItem(key: string) {
          return store[key] ?? null;
        },
        setItem(key: string, value: string) {
          store[key] = value;
        },
        removeItem(key: string) {
          delete store[key];
        },
      },
    });
  });

  it("tracks onboarding completion", () => {
    expect(hasCompletedOnboarding()).toBe(false);
    markOnboardingComplete();
    expect(hasCompletedOnboarding()).toBe(true);
  });

  it("consumes oauth pending flag once", () => {
    setOnboardingOAuthPending();
    expect(consumeOnboardingOAuthPending()).toBe(true);
    expect(consumeOnboardingOAuthPending()).toBe(false);
  });
});
