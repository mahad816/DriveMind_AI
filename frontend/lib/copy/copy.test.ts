import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { DriveFileRead } from "@/lib/api/types";
import type { PreparationQueueState } from "@/lib/knowledge/preparation-queue";
import { trayModel } from "./preparation";

// Blueprint §17 (copy): no user-facing string may contain internal stage names, status codes or "beta owner".
const BANNED = [/\bchunk/i, /\bingest/i, /\bindex(ed|ing)?\b/i, /beta owner/i, /\bjob id\b/i, /\b(4|5)\d\d\b/, /\bINGEST|CHUNK|BUILD\b/];
function strings(source: string): string[] {
  // String literals and JSX text nodes.
  const literals = [...source.matchAll(/"([^"\\\n]{3,})"|`([^`]{3,})`|'([^'\\\n]{3,})'/g)].map(m => m[1] ?? m[2] ?? m[3]);
  const jsx = [...source.matchAll(/>\s*([^<>{}\n][^<>{}]{2,}?)\s*</g)].map(m => m[1]);
  return [...literals, ...jsx].filter(s => /[a-z] [a-z]/i.test(s));
}
function walk(dir: string): string[] {
  return readdirSync(dir).flatMap(name => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : /\.tsx?$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}

describe("user-facing copy", () => {
  it.each(["lib/copy", "components"])("%s has no internal vocabulary in sentences", root => {
    const offenders: string[] = [];
    for (const file of walk(root)) {
      for (const text of strings(readFileSync(file, "utf8"))) {
        // Code-like fragments (class lists, identifiers, imports, URLs) are not sentences people read.
        if (/^[a-z0-9:_\-[\]()./%&>= ]+$/.test(text) && !/[A-Z]/.test(text) && text.split(" ").every(w => /[-:[\]]/.test(w) || w.length < 3 || /^[a-z]+$/.test(w)) && /(-|:|\[)/.test(text)) continue;
        if (/^(@\/|\.\/|https?:|\/api)/.test(text) || /[{};=]/.test(text)) continue;
        if (BANNED.some(pattern => pattern.test(text))) offenders.push(`${file}: ${text}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  const owner = "00000000-0000-4000-8000-000000000001";
  const file = (id: string, name: string): DriveFileRead => ({ id, user_id: owner, drive_file_id: id, name, mime_type: "text/plain", folder_path: null,
    modified_at: "2026-01-01T00:00:00Z", indexed_at: null, status: "discovered", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" });
  const ids = ["00000000-0000-4000-8000-0000000000a1", "00000000-0000-4000-8000-0000000000a2"];
  const queue = (current: number, results: ("pending" | "ready" | "failed" | "skipped")[]) => ({
    schemaVersion: 3 as const, batchId: "00000000-0000-4000-8000-0000000000b1", owner, current,
    entries: ids.map((fileId, i) => ({ fileId, runId: `00000000-0000-4000-8000-0000000000c${i}`, frame: "f", receipts: [], result: results[i] })),
  });
  const files = [file(ids[0], "Methods.txt"), file(ids[1], "Budget.txt")];
  const state = (s: Partial<PreparationQueueState>): PreparationQueueState => ({ phase: "idle", queue: null, child: null, message: "internal", ...s });

  it("hides the tray when there is no queue, and never shows the controller's internal message", () => {
    expect(trayModel(state({}), files).visible).toBe(false);
    const model = trayModel(state({ phase: "review", queue: queue(0, ["pending", "pending"]) }), files);
    expect(JSON.stringify(model)).not.toContain("internal");
    expect(model.primary).toEqual({ action: "confirm", label: "Prepare first document" });
  });
  it("offers the next document only between documents, and summarises a mixed finish honestly", () => {
    const between = trayModel(state({ phase: "awaiting_next", queue: queue(1, ["failed", "pending"]) }), files);
    expect(between.primary?.label).toBe("Prepare next document");
    expect(between.summary).toContain("couldn't be prepared");
    const done = trayModel(state({ phase: "complete", queue: queue(2, ["ready", "failed"]) }), files);
    expect(done.summary).toBe("1 ready, 1 couldn't be prepared. Ready documents can be used in answers; your Drive wasn't changed.");
  });
  it("a paused queue never offers to prepare; it offers to check or reconnect", () => {
    const unknown = trayModel(state({ phase: "blocked", queue: queue(0, ["pending", "pending"]),
      child: { phase: "unknown", file: null, job: null, stage: "INGEST", message: "", canRelease: false, connected: true } }), files);
    expect(unknown.primary?.action).toBe("check");
    expect(unknown.summary).toContain("won't send it again");
    const disconnected = trayModel(state({ phase: "blocked", queue: queue(0, ["pending", "pending"]),
      child: { phase: "failed", file: null, job: null, stage: "INGEST", message: "", canRelease: true, connected: false } }), files);
    expect(disconnected.primary?.action).toBe("reconnect");
  });
  it("a server-side failure not pinned on the document says so, instead of claiming progress is unconfirmed", () => {
    const job = { id: "j", status: "failed", operation: "INGEST" } as unknown as NonNullable<PreparationQueueState["child"]>["job"];
    const model = trayModel(state({ phase: "blocked", queue: queue(1, ["ready", "pending"]),
      child: { phase: "blocked", file: null, job, stage: "INGEST", message: "", canRelease: true, connected: true } }), files);
    expect(model.summary).toContain("“Budget.txt” stopped on the server");
    expect(model.summary).not.toContain("couldn't be confirmed");
    expect(model.secondary.map(a => a.action)).toContain("end");
  });
});
