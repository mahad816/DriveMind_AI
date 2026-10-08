import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeEach, expect, it, vi } from "vitest";
const originalMode = vi.hoisted(() => { const old = process.env.NEXT_PUBLIC_DEMO_MODE; process.env.NEXT_PUBLIC_DEMO_MODE = "true"; return old; });
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { listDriveFiles } from "@/lib/api/files";
vi.mock("@/lib/hooks/use-connection-status", () => ({ useConnectionStatus: vi.fn() }));
vi.mock("@/lib/api/files", () => ({ listDriveFiles: vi.fn() }));
vi.mock("@/lib/knowledge/storage", () => ({ getLastPreparedAt: () => null, formatLastPreparedAt: () => null }));
const refetch = vi.fn(async () => {});
beforeEach(() => { vi.clearAllMocks(); vi.mocked(useConnectionStatus).mockReturnValue({ data: { connected: false, job: null, demo_mode: true, demo_ready: true }, error: null, isLoading: false, refetch }); });
afterEach(cleanup);
afterAll(() => { if (originalMode === undefined) delete process.env.NEXT_PUBLIC_DEMO_MODE; else process.env.NEXT_PUBLIC_DEMO_MODE = originalMode; });
it("uses authoritative demo readiness without fetching an inventory or requiring OAuth", async () => {
  const { result } = renderHook(() => useKnowledgeStatus({ pollIntervalMs: 0 }));
  expect(result.current.isReady).toBe(true); expect(result.current.setupState).toBe("ready");
  expect(result.current.needsConnect).toBe(false); expect(listDriveFiles).not.toHaveBeenCalled();
  await act(async () => { await result.current.refresh(); });
  expect(refetch).toHaveBeenCalledOnce(); expect(listDriveFiles).not.toHaveBeenCalled();
});
it("does not infer readiness from demo mode alone", () => {
  vi.mocked(useConnectionStatus).mockReturnValue({ data: { connected: false, job: null, demo_mode: true, demo_ready: false }, error: null, isLoading: false, refetch });
  const { result } = renderHook(() => useKnowledgeStatus()); expect(result.current.isReady).toBe(false); expect(result.current.setupState).toBe("error"); expect(listDriveFiles).not.toHaveBeenCalled();
});
it("fails closed while checking and after a failed status request", () => {
  vi.mocked(useConnectionStatus).mockReturnValue({ data: null, error: null, isLoading: true, refetch });
  const { result, rerender } = renderHook(() => useKnowledgeStatus()); expect(result.current.setupState).toBe("checking");
  vi.mocked(useConnectionStatus).mockReturnValue({ data: null, error: "Offline", isLoading: false, refetch }); rerender();
  expect(result.current.isReady).toBe(false); expect(result.current.error).toBe("Offline");
});

it("still loads inventory when a demo count display explicitly requires it", async () => {
  vi.mocked(listDriveFiles).mockResolvedValue({ files: [], total: 0 });
  const { result } = renderHook(() => useKnowledgeStatus({ includeInventory: true, pollIntervalMs: 0 }));
  await waitFor(() => expect(listDriveFiles).toHaveBeenCalledOnce());
  expect(result.current.isReady).toBe(false);
});
