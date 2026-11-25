import { describe, expect, it } from "vitest";
import type { DriveFileRead, DriveFileStatus } from "@/lib/api/types";
import { countViews, matches, normalize, selectPage, PAGE_SIZE } from "./library";

const file = (name: string, status: DriveFileStatus, modified = "2026-01-01T00:00:00Z", folder: string | null = null): DriveFileRead => ({
  id: name, user_id: "u", drive_file_id: name, name, mime_type: "text/plain", folder_path: folder, modified_at: modified,
  indexed_at: null, status, created_at: modified, updated_at: modified,
});
const typeOf = () => "Text";

describe("library model", () => {
  it("treats separators as spaces and ignores case and accents", () => {
    expect(normalize("Final_budget-2026.v3 (copy)")).toBe("final budget 2026 v3 copy");
    expect(matches(file("Budget_2026_final.xlsx", "discovered"), "budget 2026")).toBe(true);
    expect(matches(file("Résumé notes", "discovered"), "resume")).toBe(true);
    expect(matches(file("Notes", "discovered", undefined, "Thesis/Data"), "thesis data")).toBe(true);
    expect(matches(file("Notes", "discovered"), "budget")).toBe(false);
  });
  it("view counts partition the inventory and always sum to All", () => {
    const files = [file("a", "indexed"), file("b", "discovered"), file("c", "indexing"), file("d", "failed"), file("e", "skipped")];
    const counts = countViews(files);
    expect(counts).toEqual({ ready: 1, todo: 1, working: 1, attention: 2, all: 5 });
    expect(counts.ready + counts.todo + counts.working + counts.attention).toBe(counts.all);
  });
  it("counts reflect the active filter in every view", () => {
    const files = [file("budget a", "indexed"), file("budget b", "discovered"), file("notes", "discovered")];
    expect(countViews(files, "budget")).toMatchObject({ ready: 1, todo: 1, all: 2 });
  });
  it("sorts newest first by default, pages at 50 and clamps out-of-range pages", () => {
    const files = Array.from({ length: 120 }, (_, i) => file(`f${i}`, "discovered", new Date(Date.UTC(2026, 0, 1 + i)).toISOString()));
    const first = selectPage(files, "all", "", "modified", 1, typeOf);
    expect(first.rows).toHaveLength(PAGE_SIZE);
    expect(first.rows[0].name).toBe("f119");
    expect(first.pages).toBe(3);
    expect(selectPage(files, "all", "", "modified", 99, typeOf).page).toBe(3);
  });
  it("name sort is natural (2 before 10)", () => {
    const rows = selectPage([file("Week 10", "indexed"), file("Week 2", "indexed")], "all", "", "name", 1, typeOf).rows;
    expect(rows.map(r => r.name)).toEqual(["Week 2", "Week 10"]);
  });
});
