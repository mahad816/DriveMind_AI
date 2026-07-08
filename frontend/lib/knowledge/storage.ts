const LAST_PREPARED_KEY = "drivemind:knowledge-last-prepared";

export function getLastPreparedAt(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(LAST_PREPARED_KEY);
}

export function setLastPreparedAt(isoDate = new Date().toISOString()): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(LAST_PREPARED_KEY, isoDate);
}

export function formatLastPreparedAt(isoDate: string | null): string | null {
  if (!isoDate) {
    return null;
  }
  const date = new Date(isoDate);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
