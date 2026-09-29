import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listDriveFiles } from "@/lib/api/files";
import type { DriveFileRead } from "@/lib/api/types";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";

vi.mock("@/lib/api/files", () => ({ listDriveFiles: vi.fn() }));
vi.mock("@/lib/hooks/use-connection-status", () => ({ useConnectionStatus: vi.fn() }));
vi.mock("@/lib/knowledge/storage", () => ({
  getLastPreparedAt: () => null,
  formatLastPreparedAt: () => null,
}));

const refetchConnection = vi.fn(async () => {});

function file(status: DriveFileRead["status"]): DriveFileRead {
  return {
    id: "local-file-id",
    user_id: "user-id",
    drive_file_id: "drive-file-id",
    name: "notes.txt",
    mime_type: "text/plain",
    folder_path: null,
    modified_at: "2026-01-01T00:00:00Z",
    indexed_at: status === "indexed" ? "2026-01-01T00:00:00Z" : null,
    status,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function connection(connected: boolean, error: string | null = null) {
  vi.mocked(useConnectionStatus).mockReturnValue({
    data: error ? null : { connected, job: null },
    isLoading: false,
    error,
    refetch: refetchConnection,
  });
}

describe("knowledge setup state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listDriveFiles).mockResolvedValue({ files: [], total: 0 });
  });

  afterEach(cleanup);

  it("does not interpret a failed connection check as confirmed disconnection", () => {
    connection(false, "Could not check Google Drive connection");

    const { result } = renderHook(() => useKnowledgeStatus({ pollIntervalMs: 0 }));

    expect(result.current.error).toBe("Could not check Google Drive connection");
    expect(result.current.setupState).toBe("error");
    expect(result.current.needsConnect).toBe(false);
    expect(result.current.isReady).toBe(false);
    expect(result.current.needsPrepare).toBe(false);
  });

  it("treats a confirmed disconnected response as disconnected", () => {
    connection(false);

    const { result } = renderHook(() => useKnowledgeStatus({ pollIntervalMs: 0 }));

    expect(result.current.needsConnect).toBe(true);
    expect(result.current.setupState).toBe("not_connected");
    expect(result.current.isReady).toBe(false);
    expect(result.current.needsPrepare).toBe(false);
    expect(listDriveFiles).not.toHaveBeenCalled();
  });

  it("does not call a connected Drive with zero indexed files ready", async () => {
    connection(true);

    const { result } = renderHook(() => useKnowledgeStatus({ pollIntervalMs: 0 }));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.needsConnect).toBe(false);
    expect(result.current.needsPrepare).toBe(true);
    expect(result.current.isReady).toBe(false);
    expect(result.current.setupState).toBe("connected_not_ready");
  });

  it("stays checking until the first connected file-status response arrives", async () => {
    connection(true);
    let resolveFiles!: (value: Awaited<ReturnType<typeof listDriveFiles>>) => void;
    vi.mocked(listDriveFiles).mockImplementation(() => new Promise((resolve) => {
      resolveFiles = resolve;
    }));

    const { result } = renderHook(() => useKnowledgeStatus({ pollIntervalMs: 0 }));
    expect(result.current.setupState).toBe("checking");
    expect(result.current.needsPrepare).toBe(false);
    expect(result.current.isReady).toBe(false);

    await act(async () => {
      resolveFiles({ files: [file("indexed")], total: 1 });
    });
    expect(result.current.setupState).toBe("ready");
  });

  it("keeps the existing at-least-one-indexed-file readiness rule", async () => {
    connection(true);
    vi.mocked(listDriveFiles).mockResolvedValue({ files: [file("indexed")], total: 1 });

    const { result } = renderHook(() => useKnowledgeStatus({ pollIntervalMs: 0 }));
    await waitFor(() => expect(result.current.isReady).toBe(true));

    expect(result.current.fileStats.indexed).toBe(1);
    expect(result.current.needsPrepare).toBe(false);
    expect(result.current.setupState).toBe("ready");
  });

  it("uses the latest running backend job as preparation status without inventing progress", async () => {
    vi.mocked(useConnectionStatus).mockReturnValue({
      data: {
        connected: true,
        job: {
          id: "job-1",
          user_id: "user-id",
          status: "running",
          started_at: null,
          completed_at: null,
          error: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      },
      isLoading: false,
      error: null,
      refetch: refetchConnection,
    });

    const { result } = renderHook(() => useKnowledgeStatus({ pollIntervalMs: 0 }));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.setupState).toBe("preparing");
    expect(result.current.isReady).toBe(false);
  });

  it("refreshes indexed-file readiness after preparation without a connection-state change", async () => {
    connection(true);
    vi.mocked(listDriveFiles)
      .mockResolvedValueOnce({ files: [], total: 0 })
      .mockResolvedValue({ files: [file("indexed")], total: 1 });

    const { result } = renderHook(() => useKnowledgeStatus({ pollIntervalMs: 0 }));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(listDriveFiles).toHaveBeenCalledTimes(1);
    expect(result.current.isReady).toBe(false);

    await act(async () => {
      await result.current.refresh();
    });

    expect(refetchConnection).toHaveBeenCalled();
    await waitFor(() => expect(listDriveFiles).toHaveBeenCalledTimes(2));
    expect(result.current.fileStats.indexed).toBe(1);
    expect(result.current.isReady).toBe(true);
  });
});
