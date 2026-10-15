import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { apiFetch, buildQueryString, formatApiErrorDetail } from "@/lib/api/client";

describe("formatApiErrorDetail", () => {
  it("returns string detail from FastAPI error body", () => {
    expect(formatApiErrorDetail({ detail: "No Google Drive connection found." }, "fallback")).toBe(
      "No Google Drive connection found.",
    );
  });

  it("joins validation error messages", () => {
    expect(
      formatApiErrorDetail(
        {
          detail: [
            { loc: ["body", "question"], msg: "Field required", type: "missing" },
          ],
        },
        "fallback",
      ),
    ).toBe("Field required");
  });

  it("falls back when detail is missing", () => {
    expect(formatApiErrorDetail({}, "Request failed")).toBe("Request failed");
  });
});

describe("buildQueryString", () => {
  it("serializes defined query params", () => {
    expect(buildQueryString({ full: true, file_id: "abc-123" })).toBe(
      "?full=true&file_id=abc-123",
    );
  });

  it("omits null and undefined params", () => {
    expect(buildQueryString({ full: false, file_id: undefined })).toBe("?full=false");
  });
});

describe("apiFetch", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns parsed JSON on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ status: "ok" }),
      }),
    );

    await expect(apiFetch("/health")).resolves.toEqual({ status: "ok" });
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/health",
      expect.objectContaining({
        headers: expect.objectContaining({
          Accept: "application/json",
        }),
      }),
    );
  });

  it("throws ApiError with FastAPI detail on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: async () => ({ detail: "Service unavailable" }),
      }),
    );

    await expect(apiFetch("/chat", { method: "POST", body: "{}" })).rejects.toEqual(
      new ApiError(503, "Service unavailable", { detail: "Service unavailable" }),
    );
  });

  it("does not send JSON content-type for GET requests", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ connected: true, job: null }),
      }),
    );

    await apiFetch("/index/status");
    const [, requestInit] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(requestInit.headers).toMatchObject({
      Accept: "application/json",
    });
    expect(requestInit.headers).not.toHaveProperty("Content-Type");
  });
});

it("records a receipt before revision fencing but never returns stale private data", async () => {
  const { invalidateSessionRequests } = await import("@/lib/api/session-events");
  const receipt = vi.fn(async (response: Response) => { expect(response.status).toBe(202); });
  vi.stubGlobal("fetch", vi.fn(async () => {
    invalidateSessionRequests();
    return new Response(JSON.stringify({ job_id: "synthetic" }), { status: 202, headers: { "Content-Type": "application/json" } });
  }));
  await expect(apiFetch("/index/sync", { method: "POST", onResponseReceipt: receipt })).rejects.toMatchObject({ status: 409 });
  expect(receipt).toHaveBeenCalledOnce();
  vi.unstubAllGlobals();
});

it("current-session 401 invalidates even when receipt observation throws, preserving the API error", async () => {
  const { SESSION_INVALID_EVENT, setSessionOwner } = await import("@/lib/api/session-events");
  const target = new EventTarget(), invalid = vi.fn(() => setSessionOwner(null));
  target.addEventListener(SESSION_INVALID_EVENT, invalid);
  vi.stubGlobal("window", target);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Session expired" }), { status: 401 })));
  try {
    await expect(apiFetch("/index/sync", { onResponseReceipt: async () => { throw new Error("Storage denied"); } }))
      .rejects.toMatchObject({ status: 401, detail: "Session expired" });
    expect(invalid).toHaveBeenCalledOnce();
  } finally { vi.unstubAllGlobals(); }
});

it("stale-revision 401 with a throwing observer cannot invalidate the newer session", async () => {
  const { SESSION_INVALID_EVENT, invalidateSessionRequests, setSessionOwner, sessionOwner } = await import("@/lib/api/session-events");
  const target = new EventTarget(), invalid = vi.fn();
  target.addEventListener(SESSION_INVALID_EVENT, invalid);
  vi.stubGlobal("window", target);
  setSessionOwner("original");
  vi.stubGlobal("fetch", vi.fn(async () => {
    invalidateSessionRequests(); setSessionOwner("newer");
    return new Response(JSON.stringify({ detail: "Session expired" }), { status: 401 });
  }));
  try {
    await expect(apiFetch("/index/sync", { onResponseReceipt: async () => { throw new Error("Lock rejected"); } }))
      .rejects.toMatchObject({ status: 409 });
    expect(invalid).not.toHaveBeenCalled(); expect(sessionOwner()).toBe("newer");
  } finally { vi.unstubAllGlobals(); setSessionOwner(null); }
});

it("successful HTTP response with failed receipt bookkeeping rejects rather than returning success", async () => {
  const failure = new Error("Receipt storage failed");
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "queued" }), { status: 202 })));
  try {
    await expect(apiFetch("/index/sync", { onResponseReceipt: async () => { throw failure; } })).rejects.toBe(failure);
  } finally { vi.unstubAllGlobals(); }
});

it("HTTP error propagation takes precedence over a throwing receipt observer", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Unavailable" }), { status: 503 })));
  try {
    await expect(apiFetch("/index/sync", { onResponseReceipt: async () => { throw new Error("Bookkeeping failed"); } }))
      .rejects.toMatchObject({ status: 503, detail: "Unavailable" });
  } finally { vi.unstubAllGlobals(); }
});
