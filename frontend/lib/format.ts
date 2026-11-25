/** Dates as people say them: "Today, 14:02", "Yesterday", "Mon", "12 Nov", "12 Nov 2024". */
export function friendlyDate(value: string | null | undefined, now = new Date()): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(date)) / 86_400_000);
  const time = date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (days === 0) return `Today, ${time}`;
  if (days === 1) return "Yesterday";
  if (days > 1 && days < 7) return date.toLocaleDateString(undefined, { weekday: "long" });
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", ...(date.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}) });
}

export function fullDate(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export type HistoryGroup = "Today" | "Previous 7 days" | "Previous 30 days" | "Older";
export function historyGroup(value: string, now = new Date()): HistoryGroup {
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const at = Date.parse(value);
  if (at >= startToday) return "Today";
  if (at >= startToday - 7 * 86_400_000) return "Previous 7 days";
  if (at >= startToday - 30 * 86_400_000) return "Previous 30 days";
  return "Older";
}

export const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`;
