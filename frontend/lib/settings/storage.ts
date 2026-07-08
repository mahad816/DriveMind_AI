const CONNECTED_EMAIL_KEY = "drivemind:connected-email";

export function getConnectedEmail(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(CONNECTED_EMAIL_KEY);
}

export function setConnectedEmail(email: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(CONNECTED_EMAIL_KEY, email);
}

export function clearConnectedEmail(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(CONNECTED_EMAIL_KEY);
}
