import { ChatApiStatusCard } from "@/components/chat/chat-api-status-card";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/layout/page-header";

export default function ChatPage() {
  return (
    <PageContainer>
      <PageHeader
        title="Chat"
        description="Answers from your indexed Drive files with citations."
      />
      <ChatApiStatusCard />
    </PageContainer>
  );
}
