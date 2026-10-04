import { cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const originalMode = vi.hoisted(() => {
  const original = process.env.NEXT_PUBLIC_DEMO_MODE;
  process.env.NEXT_PUBLIC_DEMO_MODE = "true";
  return original;
});

import { ToastProvider } from "@/components/ui/toast-provider";
import { ChatInterface } from "@/components/chat/chat-interface";
import { EmptyStateHero } from "@/components/chat/empty-state-hero";
import { CitationPreview } from "@/components/chat/citation-preview";
import { FilePreviewPanel } from "@/components/files/file-preview-panel";
import { KnowledgeLibrary } from "@/components/files/knowledge-library";
import { OnboardingAwareHomeRedirect, OnboardingGate } from "@/components/onboarding/onboarding-gate";
import { OnboardingFlow } from "@/components/onboarding/onboarding-flow";
import { SettingsPageContent } from "@/components/settings/settings-page-content";
import { SourceTrustPanel } from "@/components/sources/source-trust-panel";
import { askQuestion } from "@/lib/api/chat";
import { listDriveFiles } from "@/lib/api/files";
import { getDriveSyncStatus } from "@/lib/api/indexing";
import type { DriveFileRead, DriveSyncStatusResponse } from "@/lib/api/types";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";
import { useOAuthSettingsCallback } from "@/lib/hooks/use-oauth-settings-callback";
import { prepareSingleFile } from "@/lib/knowledge/prepare-file";
import { prepareKnowledge } from "@/lib/knowledge/prepare";
import { fetchFileTextPreview } from "@/lib/files/preview";
import { createConversation, listConversations } from "@/lib/conversations/storage";
import { getConversationMessages, saveConversationMessages } from "@/lib/conversations/messages";
import { knowledgeAvailable } from "@/lib/demo";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
const params = new URLSearchParams();
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/chat", useSearchParams: () => params }));
vi.mock("@/lib/api/chat", () => ({ askQuestion: vi.fn() }));
vi.mock("@/lib/api/files", () => ({ listDriveFiles: vi.fn(), getDriveFileContentUrl: () => "/sample-content" }));
vi.mock("@/lib/api/indexing", () => ({ getDriveSyncStatus: vi.fn() }));
vi.mock("@/lib/hooks/use-connection-status", () => ({ useConnectionStatus: vi.fn() }));
vi.mock("@/lib/hooks/use-oauth-settings-callback", () => ({ useOAuthSettingsCallback: vi.fn() }));
vi.mock("@/lib/knowledge/prepare-file", () => ({ prepareSingleFile: vi.fn() }));
vi.mock("@/lib/knowledge/prepare", () => ({ prepareKnowledge: vi.fn() }));
vi.mock("@/components/settings/settings-appearance-section", () => ({ SettingsAppearanceSection: () => <section>Appearance</section> }));

const question = "When is the HarborDesk pilot launch?";
const ready: DriveSyncStatusResponse = { connected: false, job: null, demo_mode: true, demo_ready: true, demo_questions: [question] };
const file: DriveFileRead = {
  id: "demo-file", user_id: "demo-user", drive_file_id: "demo:sample", name: "launch_plan.txt",
  mime_type: "text/plain", folder_path: "/HarborDesk samples", status: "indexed",
  modified_at: "2030-03-12T00:00:00Z", indexed_at: "2030-03-12T00:00:00Z",
  created_at: "2030-03-12T00:00:00Z", updated_at: "2030-03-12T00:00:00Z",
};

function status(data: DriveSyncStatusResponse = ready) {
  vi.mocked(useConnectionStatus).mockReturnValue({ data, isLoading: false, error: null, refetch: vi.fn(async () => {}) });
}

beforeEach(() => {
  vi.clearAllMocks();
  status();
  vi.mocked(listDriveFiles).mockResolvedValue({ files: [file], total: 1 });
  vi.mocked(getDriveSyncStatus).mockResolvedValue(ready);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, text: async () => "March 25: pilot launch.\n\nMarch 20: go/no-go review." }));
  const storage = new Map<string, string>();
  Object.defineProperty(window, "localStorage", { configurable: true, value: {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  } });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
afterAll(() => {
  if (originalMode === undefined) delete process.env.NEXT_PUBLIC_DEMO_MODE;
  else process.env.NEXT_PUBLIC_DEMO_MODE = originalMode;
});

describe("public demo experience", () => {
  it("never reuses normal browser conversation history on the same origin", () => {
    const normalHistory = JSON.stringify([{ id: "normal", title: "Normal-only chat", createdAt: "2030-01-01", updatedAt: "2030-01-01" }]);
    window.localStorage.setItem("drivemind:conversations", normalHistory);
    window.localStorage.setItem("drivemind:conversation-messages:normal", JSON.stringify([{ id: "turn", question: "Normal-only question", status: "done" }]));
    expect(listConversations()).toEqual([]);
    expect(getConversationMessages("normal")).toEqual([]);
    const demo = createConversation("Demo chat");
    saveConversationMessages(demo.id, []);
    expect(listConversations().map((item) => item.title)).toEqual(["Demo chat"]);
    expect(window.localStorage.getItem("drivemind:conversations")).toBe(normalHistory);
    expect(window.localStorage.getItem(`drivemind:demo:conversation-messages:${demo.id}`)).toBe("[]");
  });

  it("uses real demo readiness without claiming Google Drive connection", async () => {
    const { result } = renderHook(() => useKnowledgeStatus({ pollIntervalMs: 0 }));
    await waitFor(() => expect(result.current.isReady).toBe(true));
    expect(result.current.isConnected).toBe(false);
    expect(result.current.needsConnect).toBe(false);
    expect(result.current.needsPrepare).toBe(false);
    expect(knowledgeAvailable({ ...ready, demo_ready: false })).toBe(false);
    expect(knowledgeAvailable({ connected: true, job: null })).toBe(false);
  });

  it("does not turn indexed file metadata alone into demo readiness", async () => {
    status({ ...ready, demo_ready: false });
    const { result } = renderHook(() => useKnowledgeStatus({ pollIntervalMs: 0 }));
    await waitFor(() => expect(result.current.setupState).toBe("error"));
    expect(result.current.isReady).toBe(false);
    expect(result.current.needsConnect).toBe(false);
  });

  it("bypasses onboarding and takes the home visitor to chat", async () => {
    render(<><OnboardingGate><div>Chat reachable</div></OnboardingGate><OnboardingAwareHomeRedirect /></>);
    expect(screen.getByText("Chat reachable")).toBeInTheDocument();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/chat"));
    expect(router.replace).not.toHaveBeenCalledWith("/onboarding");
  });

  it("direct setup and settings pages offer no Drive or rebuild actions", async () => {
    render(<><OnboardingFlow /><SettingsPageContent /></>);
    await screen.findByText("1 sample files ready");
    expect(screen.queryByRole("button", { name: /Connect Google Drive|Prepare knowledge|Refresh knowledge/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Connect Google Drive" })).not.toBeInTheDocument();
    expect(useOAuthSettingsCallback).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    expect(prepareKnowledge).not.toHaveBeenCalled();
  });

  it("shows sample messaging and sends a suggested question through the real chat API client", async () => {
    vi.mocked(askQuestion).mockResolvedValue({ query_id: "query", user_id: "demo-user", answer: "The planned pilot is March 25, 2030.", citations: [], retrieval_count: 1, message: "Answer generated" });
    const conversation = createConversation("HarborDesk demo");
    render(<ToastProvider><ChatInterface conversationId={conversation.id} /></ToastProvider>);
    expect(screen.getByText(/seven fictional product-team documents/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: question }));
    await waitFor(() => expect(askQuestion).toHaveBeenCalled());
    expect(vi.mocked(askQuestion).mock.calls[0][0].question).toBe(question);
    expect(screen.queryByText("Connect your knowledge")).not.toBeInTheDocument();
  });

  it("offers no suggestions when the sample index is unavailable", () => {
    const send = vi.fn();
    render(<EmptyStateHero demoReady={false} suggestions={[question]} needsConnect={false} needsPrepare={false} isSending={false} onSuggestionClick={send} />);
    expect(screen.getByRole("status")).toHaveTextContent("sample knowledge base is unavailable");
    expect(screen.queryByRole("button", { name: question })).not.toBeInTheDocument();
  });

  it("lists and previews samples without offering Drive links or index mutations", async () => {
    render(<KnowledgeLibrary />);
    expect(await screen.findByRole("heading", { name: file.name })).toBeInTheDocument();
    expect(await screen.findByText(/March 25: pilot launch/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open in Google Drive" })).not.toBeInTheDocument();
    cleanup();
    render(<FilePreviewPanel file={{ ...file, status: "failed" }} />);
    expect(screen.queryByRole("button", { name: "Prepare this file for chat" })).not.toBeInTheDocument();
    expect(prepareSingleFile).not.toHaveBeenCalled();
    expect(await fetchFileTextPreview(file.id, file.mime_type)).toContain("\n\n");
  });

  it("keeps full source evidence and citation popovers without fabricated Drive links", () => {
    render(<><SourceTrustPanel filename={file.name} excerpt="March 25: pilot launch." driveFileId={file.id} askHref="/chat" /><CitationPreview citation={{ chunk_id: "chunk", drive_file_id: file.id, filename: file.name, snippet: "March 25", score: 1 }} number={1} onOpenEvidence={vi.fn()} /></>);
    expect(screen.getByText(/March 25: pilot launch/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open in Google Drive" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View citation 1" }));
    expect(screen.getByRole("button", { name: "View full evidence" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open in Google Drive" })).not.toBeInTheDocument();
  });

  it("fails safely if the backend disagrees with the frontend demo setting", async () => {
    vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: null });
    const actual = await vi.importActual<typeof import("@/lib/hooks/use-connection-status")>("@/lib/hooks/use-connection-status");
    const { result } = renderHook(() => actual.useConnectionStatus({ pollIntervalMs: 0 }));
    await waitFor(() => expect(result.current.error).toContain("modes do not match"));
    expect(result.current.data).toBeNull();
  });
});
