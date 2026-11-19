import { expect, it } from "vitest";
import { JoinedCheck } from "./joined-check";

const deferred = () => { let resolve!: () => void; const promise = new Promise<void>(r => { resolve = r; }); return { promise, resolve }; };
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

it("overlapping callers share ONE run and all resolve only when it finishes", async () => {
  const gate = new JoinedCheck(), release = deferred(); let runs = 0;
  const body = async () => { runs += 1; await release.promise; };
  const a = gate.join(body), b = gate.join(body), c = gate.join(body);
  let done = 0; [a, b, c].forEach(p => void p.then(() => { done += 1; }));
  await tick();
  expect(runs).toBe(1); expect(done).toBe(0);                     // nobody is told "done" early
  release.resolve(); await Promise.all([a, b, c]);
  expect(done).toBe(3);
});

it("a call after the run finished starts a NEW run (no stale cached result)", async () => {
  const gate = new JoinedCheck(); let runs = 0;
  await gate.join(async () => { runs += 1; }); await gate.join(async () => { runs += 1; });
  expect(runs).toBe(2);
});

it("a call during another operation waits for it, then runs exactly once", async () => {
  const gate = new JoinedCheck(); let runs = 0; const order: string[] = [];
  gate.busy = true;                                               // e.g. a submit or confirm is in progress
  const body = async () => { runs += 1; order.push("check"); };
  const a = gate.join(body), b = gate.join(body);
  await tick(); expect(runs).toBe(0);
  order.push("operation done"); gate.busy = false;
  await Promise.all([a, b]);
  expect(order).toEqual(["operation done", "check"]);
  expect(runs).toBe(1);                                           // the two waiters share one check
});

it("a waiter is woken even when the operation ends with an error path (busy simply cleared)", async () => {
  const gate = new JoinedCheck(); gate.busy = true;
  const waiting = gate.join(async () => undefined); gate.busy = false;
  await expect(waiting).resolves.toBeUndefined();
});

it("a failing run rejects its joiners and does not wedge later calls", async () => {
  const gate = new JoinedCheck(), release = deferred();
  const failing = () => release.promise.then(() => { throw new Error("boom"); });
  const a = gate.join(failing), b = gate.join(failing);
  const results = Promise.allSettled([a, b]); release.resolve();
  expect((await results).map(r => r.status)).toEqual(["rejected", "rejected"]);
  await expect(gate.join(async () => undefined)).resolves.toBeUndefined();
});

it("busy reflects what controllers set, and is not held after the run", async () => {
  const gate = new JoinedCheck();
  await gate.join(async () => { gate.busy = true; try { await tick(); } finally { gate.busy = false; } });
  expect(gate.busy).toBe(false);
});
