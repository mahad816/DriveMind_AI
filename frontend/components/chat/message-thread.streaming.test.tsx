import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MessageThread, type ChatTurn } from "./message-thread";
import fixture from "@/lib/api/fixtures/conversation-backend-dto.json";
vi.mock("@/components/ui/toast-provider", () => ({ useToast: () => ({ pushToast: vi.fn() }) }));

afterEach(cleanup);
const props = { onSourceSelect: vi.fn(), onRetry: vi.fn(), onFollowUp: vi.fn(), isSending: true };
it("renders provisional text as plain unverified text with no source links or message actions", () => {
  const partial: ChatTurn = { id: "stream", question: "Question", status: "loading", error: null,
    provisional: { phase: "generating", text: "Unverified [1] [source_1] <script>example</script>" } };
  const { rerender } = render(<MessageThread {...props} messages={[partial]} />);
  expect(screen.getByLabelText("Unverified response")).toHaveTextContent("Unverified [1]");
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /copy|sources/i })).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("not yet verified");
  rerender(<MessageThread {...props} messages={[{ id: "stream", question: "Question", status: "error", error: "Verification failed", response: null }]} />);
  expect(screen.queryByLabelText("Unverified response")).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Verification failed");
});

it("uses the existing verified response renderer only after completion", () => {
  render(<MessageThread {...props} isSending={false} messages={[{ id: "stream", question: "Question", status: "done", error: null,
    response: { query_id: fixture.submission.turn.query_id, user_id: "owner", answer: fixture.submission.turn.answer,
      citations: fixture.submission.turn.citations, retrieval_count: 1, message: "Verified" } }]} />);
  expect(screen.getByText("Answer ready")).toBeInTheDocument();
  expect(screen.queryByLabelText("Unverified response")).not.toBeInTheDocument();
});
