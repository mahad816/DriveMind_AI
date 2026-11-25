import { expect, it } from "vitest";
import { describeDiscovery } from "./discovery-copy";
import type { DiscoveryState } from "./discovery";

const job = (status: string, extra = {}) => ({ id: "j", user_id: "u", operation: "SYNC", status, ...extra }) as DiscoveryState["job"];
const state = (over: Partial<DiscoveryState>): DiscoveryState => ({ phase: "idle", job: null, message: "raw", connected: true, syncAvailable: true, ...over });
const some = { total: 24, indexed: 0 }, none = { total: 0, indexed: 0 };

it.each([
  ["disconnected, never synced", state({ connected: false }), none, "Connect Google Drive to find your files."],
  ["disconnected after files existed (revoked)", state({ connected: false }), some, "Your Google Drive connection needs to be renewed."],
  ["connected, never synced", state({}), none, "Google Drive is connected. Sync to find your files."],
  ["executor closed", state({ syncAvailable: false }), none, "Sync is temporarily unavailable. Please try again."],
  ["running", state({ phase: "active", job: job("running") }), none, "Finding files in your Google Drive…"],
  ["queued", state({ phase: "active", job: job("queued") }), none, "Finding files in your Google Drive…"],
  ["complete with files", state({ phase: "complete", job: job("completed") }), some, "Sync complete. 24 files found."],
  ["complete with one file", state({ phase: "complete", job: job("completed") }), { total: 1, indexed: 0 }, "Sync complete. 1 file found."],
  ["complete with zero files", state({ phase: "complete", job: job("completed") }), none, "No supported files were found in this Drive."],
  ["failed", state({ job: job("failed") }), none, "Sync failed. Your Google Drive files were not changed. Check status before trying again."],
  ["discovered, not prepared", state({}), some, "Files found. Select a file to prepare it for chat."],
  ["some ready for chat", state({}), { total: 24, indexed: 3 }, "3 files are ready for chat. Select a file to prepare more."],
])("%s", (_name, s, inventory, message) => {
  expect(describeDiscovery(s, inventory).message).toBe(message);
});
it("offers Retry only after a failure or a known refusal, and never when work is in progress", () => {
  expect(describeDiscovery(state({ job: job("failed") }), none)).toMatchObject({ actionLabel: "Retry sync", canSync: true });
  expect(describeDiscovery(state({ phase: "unavailable" }), none)).toMatchObject({ actionLabel: "Retry sync", canSync: true });
  expect(describeDiscovery(state({ phase: "active", job: job("running") }), none)).toMatchObject({ canSync: false });
  expect(describeDiscovery(state({ syncAvailable: false }), none).canSync).toBe(false);
  expect(describeDiscovery(state({}), none)).toMatchObject({ actionLabel: "Sync Drive", canSync: true });
});
it("never shows a percentage or raw backend text", () => {
  const texts = [state({ phase: "active", job: job("running", { processed: 3, total: 10 }) }), state({ job: job("failed", { error: "boom: traceback" }) })]
    .map(s => describeDiscovery(s, none).message);
  for (const t of texts) { expect(t).not.toMatch(/%|boom|traceback|\{/); }
});
