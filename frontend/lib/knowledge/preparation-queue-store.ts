import {
  preparationKey, validatePreparationRecord,
  type PreparationRecord, type PreparationStore,
} from "./single-file-preparation";

export type QueueEntry = PreparationRecord & { result: "pending" | "ready" | "failed" | "skipped" };
export type PreparationQueueRecord = {
  schemaVersion: 2;
  batchId: string;
  owner: string;
  entries: QueueEntry[];
  current: number;
};
export type PreparationGate =
  | { kind: "empty" }
  | { kind: "legacy"; record: PreparationRecord }
  | { kind: "queue"; record: PreparationQueueRecord };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const coordinationKey = (owner: string) => `drivemind:discovery:v1:${owner}`;
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

function validateQueue(value: unknown, owner: string): asserts value is PreparationQueueRecord {
  const r = value as PreparationQueueRecord;
  if (!r || r.schemaVersion !== 2 || !uuid.test(r.batchId) || r.owner !== owner || !uuid.test(owner) ||
      !Array.isArray(r.entries) || r.entries.length < 1 || r.entries.length > 5 ||
      !Number.isInteger(r.current) || r.current < 0 || r.current > r.entries.length ||
      // Intentionally incompatible with Checkpoint B's top-level record shape.
      "fileId" in r || "runId" in r || "receipts" in r) throw new Error("Invalid queue record");
  const files = new Set<string>(), runs = new Set<string>(), submissions = new Set<string>(), jobs = new Set<string>();
  r.entries.forEach((entry, index) => {
    validatePreparationRecord(entry, true);
    if (files.has(entry.fileId) || runs.has(entry.runId) ||
        !["pending", "ready", "failed", "skipped"].includes(entry.result) ||
        (index < r.current && entry.result !== "ready") ||
        (index >= r.current && entry.result === "ready") ||
        (index > r.current && (entry.result !== "pending" || entry.receipts.length !== 0)) ||
        (entry.result === "ready" && (entry.receipts.length !== 3 || entry.receipts.some(v => !v.jobId))) ||
        (["failed", "skipped"].includes(entry.result) && !entry.receipts.at(-1)?.jobId)) throw new Error("Invalid queue entry");
    files.add(entry.fileId); runs.add(entry.runId);
    for (const receipt of entry.receipts) {
      if (submissions.has(receipt.submissionId) || (receipt.jobId && jobs.has(receipt.jobId))) throw new Error("Duplicate queue receipt");
      submissions.add(receipt.submissionId);
      if (receipt.jobId) jobs.add(receipt.jobId);
    }
  });
}

/** One canonical gate. Unknown versions/invalid data remain untouched and block. */
export function readPreparationGate(owner: string): PreparationGate {
  const raw = window.localStorage.getItem(preparationKey(owner));
  if (raw === null) return { kind: "empty" };
  const value = JSON.parse(raw);
  if (value && typeof value === "object" && "schemaVersion" in value) {
    validateQueue(value, owner);
    return { kind: "queue", record: value };
  }
  validatePreparationRecord(value);
  return { kind: "legacy", record: value };
}

/** CAS the entire envelope, including cursor/history, under discovery's short lock. */
export async function replaceQueue(
  owner: string, expected: PreparationQueueRecord | null, next: PreparationQueueRecord | null,
  allowed: () => boolean = () => true,
): Promise<boolean> {
  if (!navigator.locks) throw new Error("Browser coordination unavailable");
  if (next) validateQueue(next, owner);
  return navigator.locks.request(coordinationKey(owner), () => {
    if (!allowed()) return false;
    const gate = readPreparationGate(owner);
    if (gate.kind === "legacy" || !same(gate.kind === "queue" ? gate.record : null, expected)) return false;
    if (expected === null && window.localStorage.getItem(coordinationKey(owner)) !== null) return false;
    if (next) window.localStorage.setItem(preparationKey(owner), JSON.stringify(next));
    else window.localStorage.removeItem(preparationKey(owner));
    return true;
  });
}

export const childRecord = (entry: QueueEntry): PreparationRecord => ({
  fileId: entry.fileId, runId: entry.runId, frame: entry.frame, receipts: entry.receipts,
});

/** Bound forever to one batch/cursor/run. Receipt persistence may outlive its UI. */
export function queueChildStore(owner: string, batch: PreparationQueueRecord): PreparationStore {
  const index = batch.current, identity = batch.entries[index];
  function current() {
    const gate = readPreparationGate(owner);
    if (gate.kind !== "queue" || gate.record.batchId !== batch.batchId || gate.record.current !== index ||
        gate.record.entries[index]?.runId !== identity.runId || gate.record.entries[index]?.fileId !== identity.fileId) {
      throw new Error("Queue workflow changed");
    }
    return gate.record;
  }
  return {
    read: () => childRecord(current().entries[index]),
    replace: async (expected, next) => {
      // Closing a child must never remove the owner-wide batch gate.
      if (!expected || !next || next.runId !== identity.runId || next.fileId !== identity.fileId) return false;
      const before = current(), entry = before.entries[index];
      if (entry.result !== "pending" || !same(childRecord(entry), expected)) return false;
      return replaceQueue(owner, before, {
        ...before, entries: before.entries.map((v, i) => i === index ? { ...next, result: "pending" } : v),
      });
    },
  };
}
