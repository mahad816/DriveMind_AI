import { ChatApiStatusCard } from "@/components/chat/chat-api-status-card";

export default function ChatPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-6 md:p-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Chat</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Answers from your indexed Drive files with citations.
        </p>
      </div>

      <ChatApiStatusCard />
    </div>
  );
}
