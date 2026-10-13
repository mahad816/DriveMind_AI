import { afterEach, expect, it, vi } from "vitest";
import { inspectApplicationSession, logoutApplicationSession, startGoogleSession } from "./auth";
import { listDriveFiles } from "./files";
import { askQuestion } from "./chat";
import { getSourceChunk } from "./sources";
const owner = "00000000-0000-0000-0000-000000000065";
const session = { kind: "GOOGLE_ACCOUNT", user_id: owner, csrf_token: "synthetic-csrf" };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());
it("bootstraps only a verified normal session without caching or browser token storage", async () => {
  const fetch = vi.fn().mockResolvedValue(json(session)); vi.stubGlobal("fetch", fetch);
  expect(await inspectApplicationSession()).toEqual(session);
  expect(fetch).toHaveBeenCalledWith("/api/v1/auth/session", expect.objectContaining({ credentials: "include", cache: "no-store" }));
});
it.each([{ ...session, kind: "DEMO_VISITOR" }, { ...session, user_id: "editable-email" }, null])("rejects malformed/wrong-kind inspection %j", async value => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(value)));
  await expect(inspectApplicationSession()).rejects.toMatchObject({ status: 503 });
});
it("LOGIN uses the browser-bound POST protocol and no legacy fallback", async () => {
  const fetch = vi.fn().mockResolvedValue(json({ authorization_url: "https://accounts.google.com/o/oauth2/auth?state=synthetic" })); vi.stubGlobal("fetch", fetch);
  expect(await startGoogleSession("LOGIN")).toContain("https://accounts.google.com/");
  expect(fetch).toHaveBeenCalledWith("/api/v1/auth/session/google", expect.objectContaining({ method: "POST", credentials: "include", body: JSON.stringify({ intent: "LOGIN" }), headers: expect.objectContaining({ "X-DriveMind-Auth": "1" }) }));
});
it("CONNECT_DRIVE obtains current owner-bound CSRF and sends no owner field", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(json(session)).mockResolvedValueOnce(json({ authorization_url: "https://accounts.google.com/o/oauth2/auth" })); vi.stubGlobal("fetch", fetch);
  await startGoogleSession("CONNECT_DRIVE", owner);
  expect(fetch).toHaveBeenLastCalledWith("/api/v1/auth/session/google", expect.objectContaining({ headers: expect.objectContaining({ "X-CSRF-Token": "synthetic-csrf", "X-DriveMind-Auth": "1" }), body: JSON.stringify({ intent: "CONNECT_DRIVE" }) }));
});
it("rejects a switched identity before CONNECT_DRIVE or logout", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(json({ ...session, user_id: "00000000-0000-0000-0000-000000000066" }))); vi.stubGlobal("fetch", fetch);
  await expect(startGoogleSession("CONNECT_DRIVE", owner)).rejects.toMatchObject({ status: 409 });
  await expect(logoutApplicationSession(owner)).rejects.toMatchObject({ status: 409 });
  expect(fetch.mock.calls.every(([url]) => url === "/api/v1/auth/session")).toBe(true);
});
it("logout uses current CSRF, cookies and the 204 contract", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(json(session)).mockResolvedValueOnce(new Response(null, { status: 204 })); vi.stubGlobal("fetch", fetch);
  await logoutApplicationSession(owner);
  expect(fetch).toHaveBeenLastCalledWith("/api/v1/auth/session/logout", expect.objectContaining({ method: "POST", credentials: "include", headers: expect.objectContaining({ "X-CSRF-Token": "synthetic-csrf" }) }));
});
it.each([401, 403, 404, 503])("auth HTTP %s never falls back to legacy OAuth", async status => {
  const fetch = vi.fn().mockResolvedValue(json({ detail: "synthetic rejection" }, status)); vi.stubGlobal("fetch", fetch);
  await expect(startGoogleSession("LOGIN")).rejects.toMatchObject({ status });
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("private file/chat/source calls carry cookies", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(json({}))); vi.stubGlobal("fetch", fetch);
  await listDriveFiles(); await askQuestion({ question: "Synthetic question" }); await getSourceChunk("synthetic-chunk");
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/api/v1/files", "/api/v1/chat", "/api/v1/sources/synthetic-chunk"]);
  expect(fetch.mock.calls.every(([, options]) => options.credentials === "include")).toBe(true);
});
