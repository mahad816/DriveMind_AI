import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectionStatusProvider } from "@/components/providers/connection-status-provider";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { getDriveSyncStatus } from "@/lib/api/indexing";
import type { DriveSyncStatusResponse } from "@/lib/api/types";

const mode = vi.hoisted(() => ({ demo: false }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return mode.demo; } }));
vi.mock("@/lib/api/indexing", () => ({ getDriveSyncStatus: vi.fn() }));
const ready: DriveSyncStatusResponse = { connected: true, job: null };
function deferred() {
  let resolve!: (v: DriveSyncStatusResponse) => void;
  const promise = new Promise<DriveSyncStatusResponse>((r) => { resolve = r; });
  return { promise, resolve };
}
function Consumer({ name, interval = 0 }: { name: string; interval?: number }) {
  const state = useConnectionStatus({ pollIntervalMs: interval });
  return <div><output data-testid={name}>{JSON.stringify(state)}</output><button onClick={() => void state.refetch()}>Refresh {name}</button></div>;
}
function state(name = "a") { return JSON.parse(screen.getByTestId(name).textContent!); }
async function settle() { await act(async () => { await Promise.resolve(); }); }
function pair(interval = 0) {
  return render(<ConnectionStatusProvider><Consumer name="a" interval={interval} /><Consumer name="b" interval={interval} /></ConnectionStatusProvider>);
}
beforeEach(() => { vi.clearAllMocks(); mode.demo = false; vi.mocked(getDriveSyncStatus).mockResolvedValue(ready); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("application-scoped readiness requests", () => {
  it("shares one in-flight mount request and publishes the result to all consumers", async () => {
    const request = deferred(); vi.mocked(getDriveSyncStatus).mockReturnValue(request.promise);
    pair(); expect(getDriveSyncStatus).toHaveBeenCalledOnce();
    await act(async () => { request.resolve(ready); });
    expect(state("a").data).toEqual(ready); expect(state("b").data).toEqual(ready);
    expect(state().isLoading).toBe(false);
  });
  it("does not cache a failure permanently and manual retry updates every consumer", async () => {
    vi.mocked(getDriveSyncStatus).mockRejectedValueOnce(new Error("Offline"));
    pair(); await settle(); expect(state().error).toBe("Offline"); expect(state().data).toBeNull();
    fireEvent.click(screen.getByText("Refresh a")); await settle();
    expect(getDriveSyncStatus).toHaveBeenCalledTimes(2); expect(state("b").error).toBeNull();
  });
  it("clears stale successful readiness when a refresh fails", async () => {
    pair(); await settle(); vi.mocked(getDriveSyncStatus).mockRejectedValueOnce(new Error("Unavailable"));
    fireEvent.click(screen.getByText("Refresh b")); await settle(); expect(state().data).toBeNull();
  });
  it("coalesces overlapping manual refreshes into one fresh post-mutation request", async () => {
    const request = deferred(); vi.mocked(getDriveSyncStatus).mockReturnValueOnce(request.promise).mockResolvedValue({ connected: false, job: null });
    pair(); fireEvent.click(screen.getByText("Refresh a")); fireEvent.click(screen.getByText("Refresh b"));
    expect(getDriveSyncStatus).toHaveBeenCalledOnce();
    await act(async () => { request.resolve(ready); }); await settle();
    expect(getDriveSyncStatus).toHaveBeenCalledTimes(2); expect(state().data.connected).toBe(false);
  });
  it("shares polling, preserves zero-poll subscribers, and stops timers after unmount", async () => {
    vi.useFakeTimers(); const view = pair(30000); await settle();
    await act(async () => { vi.advanceTimersByTime(30000); }); expect(getDriveSyncStatus).toHaveBeenCalledTimes(2);
    view.unmount(); await act(async () => { vi.advanceTimersByTime(90000); }); expect(getDriveSyncStatus).toHaveBeenCalledTimes(2);
  });
  it("does not start polling when all consumers request zero", async () => {
    vi.useFakeTimers(); pair(); await settle(); await act(async () => { vi.advanceTimersByTime(90000); });
    expect(getDriveSyncStatus).toHaveBeenCalledOnce();
  });
  it("rechecks on remount without reusing another application instance's readiness", async () => {
    const first = pair(); await settle(); first.unmount();
    vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: false, job: null }); pair(); await settle();
    expect(state().data.connected).toBe(false); expect(getDriveSyncStatus).toHaveBeenCalledTimes(2);
  });
  it("rejects a demo response in normal mode", async () => {
    vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: false, job: null, demo_mode: true, demo_ready: true });
    pair(); await settle(); expect(state().data).toBeNull(); expect(state().error).toMatch(/modes do not match/);
  });
  it("rejects normal readiness in a new demo application rather than reusing normal state", async () => {
    const first = pair(); await settle(); first.unmount(); mode.demo = true;
    pair(); await settle(); expect(state().data).toBeNull(); expect(state().error).toMatch(/modes do not match/);
  });
  it("keeps independent providers isolated even while their requests are in flight", async () => {
    const normal = deferred(); const demo = deferred();
    vi.mocked(getDriveSyncStatus).mockReturnValueOnce(normal.promise).mockReturnValueOnce(demo.promise);
    const first = render(<ConnectionStatusProvider><Consumer name="normal" /></ConnectionStatusProvider>);
    mode.demo = true; render(<ConnectionStatusProvider><Consumer name="demo" /></ConnectionStatusProvider>);
    await act(async () => { demo.resolve({ connected: false, job: null, demo_mode: true, demo_ready: true }); normal.resolve(ready); });
    expect(state("normal").data.connected).toBe(true); expect(state("demo").data.demo_ready).toBe(true); first.unmount();
  });
  it("joins an in-flight request when a consumer unmounts and remounts inside the same provider", async () => {
    const request = deferred(); vi.mocked(getDriveSyncStatus).mockReturnValue(request.promise);
    const view = render(<ConnectionStatusProvider><Consumer name="a" /></ConnectionStatusProvider>);
    view.rerender(<ConnectionStatusProvider>{null}</ConnectionStatusProvider>);
    view.rerender(<ConnectionStatusProvider><Consumer name="a" /></ConnectionStatusProvider>);
    expect(getDriveSyncStatus).toHaveBeenCalledOnce(); await act(async () => { request.resolve(ready); }); expect(state().data).toEqual(ready);
  });
});

it("deduplicates StrictMode effect remounts", async () => {
  render(<StrictMode><ConnectionStatusProvider><Consumer name="a" /><Consumer name="b" /></ConnectionStatusProvider></StrictMode>);
  await settle(); expect(getDriveSyncStatus).toHaveBeenCalledOnce();
});
it("stops shared polling when the polling consumer leaves but a zero-poll consumer remains", async () => {
  vi.useFakeTimers();
  const view = render(<ConnectionStatusProvider><Consumer key="a" name="a" interval={30000} /><Consumer key="b" name="b" /></ConnectionStatusProvider>);
  await settle(); await act(async () => { vi.advanceTimersByTime(30000); });
  expect(getDriveSyncStatus).toHaveBeenCalledTimes(2);
  view.rerender(<ConnectionStatusProvider><Consumer key="b" name="b" /></ConnectionStatusProvider>);
  await act(async () => { vi.advanceTimersByTime(90000); }); expect(getDriveSyncStatus).toHaveBeenCalledTimes(2);
});
