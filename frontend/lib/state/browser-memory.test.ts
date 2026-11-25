// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import {
  clearAllDrafts, clearReturnPath, dropOtherOwnersDrafts, readDraft, safeReturnPath, takeConnectIntent, takeReturnPath, writeDraft,
} from "./browser-memory";

const A = "5f0c1d2e-3a4b-4c5d-8e6f-7a8b9c0d1e2f";
const B = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const C = "11111111-2222-4333-8444-555555555555";

beforeEach(() => { sessionStorage.clear(); window.history.replaceState(null, "", "/"); });

describe("drafts are owner-scoped", () => {
  it("one owner never reads another owner's draft", () => {
    writeDraft(A, null, "private question");
    expect(readDraft(A, null)).toBe("private question");
    expect(readDraft(B, null)).toBe("");
    expect(readDraft(null, null)).toBe("");
  });
  it("drafts are per conversation, and an empty draft is removed", () => {
    writeDraft(A, C, "about this one");
    expect(readDraft(A, null)).toBe("");
    writeDraft(A, C, "   ");
    expect(readDraft(A, C)).toBe("");
  });
  it("dropOtherOwnersDrafts keeps only the active owner's drafts", () => {
    writeDraft(A, null, "a"); writeDraft(A, C, "a2"); writeDraft(B, null, "b");
    dropOtherOwnersDrafts(B);
    expect(readDraft(A, null)).toBe(""); expect(readDraft(A, C)).toBe("");
    expect(readDraft(B, null)).toBe("b");
  });
  it("clearAllDrafts removes every owner's drafts and nothing else", () => {
    sessionStorage.setItem("unrelated", "keep");
    writeDraft(A, null, "a"); writeDraft(B, null, "b");
    clearAllDrafts();
    expect(readDraft(A, null)).toBe(""); expect(readDraft(B, null)).toBe("");
    expect(sessionStorage.getItem("unrelated")).toBe("keep");
  });
});

describe("return path", () => {
  it("accepts only known in-app paths", () => {
    expect(safeReturnPath("/files?view=todo")).toBe("/files?view=todo");
    expect(safeReturnPath(`/chat/${C}`)).toBe(`/chat/${C}`);
    expect(safeReturnPath(`/sources/${C}?conversation=${A}`)).toBe(`/sources/${C}?conversation=${A}`);
  });
  it.each(["//evil.example/chat", "https://evil.example/", "/chat/not-a-uuid", "/settings?login=success", "/admin", "chat", "", null])(
    "rejects %s", value => { expect(safeReturnPath(value)).toBeNull(); });
  it("is taken once, and a stored unsafe value is never returned", () => {
    sessionStorage.setItem("drivemind:return-to:v1", "/files");
    expect(takeReturnPath()).toBe("/files");
    expect(takeReturnPath()).toBeNull();
    sessionStorage.setItem("drivemind:return-to:v1", "//evil.example");
    expect(takeReturnPath()).toBeNull();
  });
  it("clearReturnPath (called on sign-out) forgets it", () => {
    sessionStorage.setItem("drivemind:return-to:v1", `/chat/${C}`);
    clearReturnPath();
    expect(takeReturnPath()).toBeNull();
  });
});

describe("connect intent", () => {
  it("is true once for the owner who started it", () => {
    sessionStorage.setItem("drivemind:connect-intent:v1", A);
    expect(takeConnectIntent(A)).toBe(true);
    expect(takeConnectIntent(A)).toBe(false);
  });
  it("is false for a different owner, and is cleared anyway", () => {
    sessionStorage.setItem("drivemind:connect-intent:v1", A);
    expect(takeConnectIntent(B)).toBe(false);
    expect(sessionStorage.getItem("drivemind:connect-intent:v1")).toBeNull();
  });
});
