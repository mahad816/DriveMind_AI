import type { DriveFileRead } from "@/lib/api/types";
import type { PreparationQueueState } from "@/lib/knowledge/preparation-queue";

/** Presentation of the kept queue controller. No safety decision is made here; the controller remains the authority. */
export type RowState = "waiting" | "starting" | "reading" | "organising" | "finishing" | "between" | "ready" | "failed" | "skipped" | "paused";
export type TrayRow = { fileId: string; name: string; state: RowState; label: string; detail?: string };
export type TrayAction = "confirm" | "reconnect" | "check" | "done" | "end";
export type TrayModel = {
  visible: boolean;
  tone: "working" | "attention" | "done" | "idle";
  headline: string;
  summary: string;
  rows: TrayRow[];
  primary: { action: TrayAction; label: string } | null;
  secondary: { action: TrayAction; label: string }[];
  /** One-line status for the collapsed pill. */
  pill: string;
  busy: boolean;
};

const ROW_LABEL: Record<RowState, string> = {
  waiting: "Waiting", starting: "Starting", reading: "Reading the document", organising: "Organising passages",
  finishing: "Making it searchable", between: "Waiting for you", ready: "Ready", failed: "Couldn't be prepared",
  skipped: "No readable text", paused: "Paused",
};
const STAGE_STATE = { INGEST: "reading", CHUNK: "organising", BUILD: "finishing" } as const;

export function trayModel(state: PreparationQueueState, files: readonly DriveFileRead[] | null): TrayModel {
  const queue = state.queue;
  const hidden: TrayModel = { visible: false, tone: "idle", headline: "", summary: "", rows: [], primary: null, secondary: [], pill: "", busy: false };
  if (state.phase === "legacy") {
    return { ...hidden, visible: true, tone: "attention", headline: "Earlier preparation needs a check",
      summary: "A preparation started by an older version of DriveMind is still recorded in this browser. Check it before preparing more documents.",
      primary: { action: "check", label: "Check again" }, secondary: [], pill: "Earlier preparation" };
  }
  if (!queue) return hidden;

  const name = (id: string) => files?.find(f => f.id === id)?.name ?? "Document";
  const child = state.child;
  const paused = state.phase === "blocked" || state.phase === "stopped";
  const rows: TrayRow[] = queue.entries.map((entry, index) => {
    let rowState: RowState;
    if (index < queue.current) rowState = entry.result === "ready" ? "ready" : entry.result === "failed" ? "failed" : "skipped";
    else if (index > queue.current) rowState = "waiting";
    else if (entry.result === "failed") rowState = "failed";
    else if (entry.result === "skipped") rowState = "skipped";
    else if (paused) rowState = "paused";
    else if (child?.phase === "submitting") rowState = child.stage ? STAGE_STATE[child.stage] : "starting";
    else if (child?.phase === "active" && child.stage) rowState = STAGE_STATE[child.stage];
    else if (child?.phase === "continue") rowState = "between";
    else rowState = "waiting";
    const detail = rowState === "failed" ? "DriveMind couldn't read this document. Your Drive wasn't changed."
      : rowState === "skipped" ? "No readable text was found, for example in a scanned PDF."
      : undefined;
    return { fileId: entry.fileId, name: name(entry.fileId), state: rowState, label: ROW_LABEL[rowState], detail };
  });

  const total = queue.entries.length;
  const ready = rows.filter(r => r.state === "ready").length;
  const unprepared = rows.filter(r => r.state === "failed" || r.state === "skipped").length;
  const position = Math.min(queue.current + 1, total);
  const working = rows.some(r => ["starting", "reading", "organising", "finishing"].includes(r.state));

  if (state.phase === "complete") {
    const summary = unprepared === 0
      ? `${ready === 1 ? "The document is" : `All ${ready} documents are`} ready. Answers can now cite ${ready === 1 ? "it" : "them"}.`
      : `${ready} ready, ${unprepared} couldn't be prepared. Ready documents can be used in answers; your Drive wasn't changed.`;
    return { visible: true, tone: "done", headline: "Preparation finished", summary, rows, busy: false,
      primary: { action: "done", label: "Done" }, secondary: [], pill: unprepared ? `${ready} ready, ${unprepared} not prepared` : `${ready} ready` };
  }
  if (paused) {
    const disconnected = child?.connected === false;
    const unknown = child?.phase === "unknown";
    // The server ended the step, but did not establish that the document itself was the cause (for example a
    // Drive or provider error). The controller then pauses the batch instead of moving on.
    const serverStopped = state.phase === "blocked" && child?.phase === "blocked" && child.canRelease && !!child.job && ["failed", "canceled"].includes(child.job.status);
    const current = rows[queue.current]?.name;
    const summary = disconnected
      ? "Google Drive isn't connected, so preparation is paused. Reconnect Drive to continue. Nothing was lost."
      : unknown
        ? "DriveMind can't confirm whether the last step finished. It won't send it again automatically. Check again in a moment."
        : serverStopped
          ? `Preparing “${current ?? "this document"}” stopped on the server, for a reason that wasn't confirmed to be the document itself, so nothing else will start. Your Drive wasn't changed. Check again later, or stop tracking; documents already ready stay ready.`
        : state.phase === "stopped"
          ? "Preparation stopped at a document that couldn't be prepared. Documents already ready stay ready."
          : "Preparation is paused because its progress couldn't be confirmed. Check again in a moment; nothing will be sent twice.";
    return { visible: true, tone: "attention", headline: "Preparation paused", summary, rows, busy: false,
      primary: disconnected ? { action: "reconnect", label: "Reconnect Google Drive" } : { action: "check", label: "Check again" },
      secondary: disconnected ? [{ action: "check", label: "Check again" }, { action: "end", label: "Stop tracking" }] : [{ action: "end", label: "Stop tracking" }],
      pill: "Preparation paused" };
  }
  if (state.phase === "review") {
    return { visible: true, tone: "idle", headline: `${total} ${total === 1 ? "document" : "documents"} selected`,
      summary: "DriveMind prepares one document at a time and asks before starting each one.", rows, busy: false,
      primary: { action: "confirm", label: "Prepare first document" }, secondary: [{ action: "end", label: "Cancel" }], pill: `${total} selected` };
  }
  if (state.phase === "awaiting_next") {
    const next = rows[queue.current];
    const last = rows[queue.current - 1];
    const lead = last?.state === "ready" ? `“${last.name}” is ready.` : last ? `“${last.name}” couldn't be prepared.` : "";
    return { visible: true, tone: "idle", headline: `Preparing ${position} of ${total}`,
      summary: `${lead} Prepare the next one when you're ready.`.trim(), rows, busy: false,
      primary: { action: "confirm", label: next ? "Prepare next document" : "Continue" },
      secondary: [{ action: "end", label: "Stop after this" }], pill: `${ready} of ${total} ready` };
  }
  // progress / checking
  const between = child?.phase === "continue" && !working;
  return { visible: true, tone: "working", headline: `Preparing ${position} of ${total}`,
    summary: between ? "The last step finished. Continue to finish this document." : "You can keep working; this continues while DriveMind is open.",
    rows, busy: working || state.phase === "checking",
    primary: between ? { action: "confirm", label: "Continue preparing" } : null, secondary: [],
    pill: `Preparing ${position} of ${total}` };
}
