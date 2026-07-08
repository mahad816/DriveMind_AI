const ONBOARDING_COMPLETE_KEY = "drivemind:onboarding-complete";
const ONBOARDING_OAUTH_KEY = "drivemind:onboarding-oauth";

export function hasCompletedOnboarding(): boolean {
  if (typeof window === "undefined") {
    return true;
  }
  return window.localStorage.getItem(ONBOARDING_COMPLETE_KEY) === "true";
}

export function markOnboardingComplete(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(ONBOARDING_COMPLETE_KEY, "true");
}

export function resetOnboardingComplete(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(ONBOARDING_COMPLETE_KEY);
}

export function setOnboardingOAuthPending(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(ONBOARDING_OAUTH_KEY, "true");
}

export function consumeOnboardingOAuthPending(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  const pending = window.localStorage.getItem(ONBOARDING_OAUTH_KEY) === "true";
  if (pending) {
    window.localStorage.removeItem(ONBOARDING_OAUTH_KEY);
  }
  return pending;
}
