import { ChatApiStatusCard } from "@/components/chat/chat-api-status-card";
import { ChatInterface } from "@/components/chat/chat-interface";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/layout/page-header";

export default function ChatPage() {
  return (
    <PageContainer size="lg" className="max-w-3xl">
      <PageHeader
        title="Chat"
        description="Ask grounded questions about your indexed Drive files."
      />

      <ChatApiStatusCard />
      <ChatInterface />
    </PageContainer>
  );
}

