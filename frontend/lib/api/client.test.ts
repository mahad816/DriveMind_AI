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
