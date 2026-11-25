import type { DriveFileRead, DriveFileStatus } from "@/lib/api/types";

/** Views partition the inventory: their counts always sum to "All" (fixes audit F-06). */
export const VIEWS = ["ready", "todo", "working", "attention", "all"] as const;
export type LibraryView = typeof VIEWS[number];
export const VIEW_LABEL: Record<LibraryView, string> = {
  ready: "Ready", todo: "To prepare", working: "Preparing", attention: "Needs attention", all: "All",
};
const VIEW_STATUSES: Record<Exclude<LibraryView, "all">, DriveFileStatus[]> = {
  ready: ["indexed"], todo: ["discovered"], working: ["indexing"], attention: ["failed", "skipped"],
};
export const inView = (file: DriveFileRead, view: LibraryView) => view === "all" || VIEW_STATUSES[view].includes(file.status);

export const SORTS = ["modified", "name", "type", "status"] as const;
export type LibrarySort = typeof SORTS[number];
export const SORT_LABEL: Record<LibrarySort, string> = { modified: "Last modified", name: "Name", type: "Type", status: "Status" };

/** Underscores, hyphens and dots count as spaces, so "budget_2026" finds "Budget 2026" (fixes audit F-03). */
export function normalize(value: string): string {
  return value.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[_\-.–—/\\()[\],]+/g, " ").replace(/\s+/g, " ").trim();
}
export function matches(file: DriveFileRead, query: string): boolean {
  const tokens = normalize(query).split(" ").filter(Boolean);
  if (!tokens.length) return true;
  const haystack = `${normalize(file.name)} ${normalize(file.folder_path ?? "")}`;
  return tokens.every(token => haystack.includes(token));
}

const STATUS_ORDER: Record<DriveFileStatus, number> = { indexed: 0, indexing: 1, discovered: 2, failed: 3, skipped: 4 };
const collator = typeof Intl !== "undefined" ? new Intl.Collator(undefined, { numeric: true, sensitivity: "base" }) : null;
export function compareFiles(sort: LibrarySort, typeOf: (mime: string) => string) {
  const byName = (a: DriveFileRead, b: DriveFileRead) => collator ? collator.compare(a.name, b.name) : a.name.localeCompare(b.name);
  return (a: DriveFileRead, b: DriveFileRead) => {
    if (sort === "name") return byName(a, b);
    if (sort === "type") return typeOf(a.mime_type).localeCompare(typeOf(b.mime_type)) || byName(a, b);
    if (sort === "status") return STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || byName(a, b);
    return Date.parse(b.modified_at) - Date.parse(a.modified_at) || byName(a, b);
  };
}

export type ViewCounts = Record<LibraryView, number>;
export function countViews(files: readonly DriveFileRead[], query = ""): ViewCounts {
  const counts: ViewCounts = { ready: 0, todo: 0, working: 0, attention: 0, all: 0 };
  for (const file of files) {
    if (!matches(file, query)) continue;
    counts.all++;
    for (const view of ["ready", "todo", "working", "attention"] as const) if (inView(file, view)) counts[view]++;
  }
  return counts;
}

export const PAGE_SIZE = 50;
export function selectPage(files: readonly DriveFileRead[], view: LibraryView, query: string, sort: LibrarySort, page: number, typeOf: (mime: string) => string) {
  const rows = files.filter(file => inView(file, view) && matches(file, query)).sort(compareFiles(sort, typeOf));
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const current = Math.min(Math.max(1, page), pages);
  return { rows: rows.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE), total: rows.length, pages, page: current };
}

export function parseView(value: string | null): LibraryView { return (VIEWS as readonly string[]).includes(value ?? "") ? value as LibraryView : "all"; }
export function parseSort(value: string | null): LibrarySort { return (SORTS as readonly string[]).includes(value ?? "") ? value as LibrarySort : "modified"; }
