import { Suspense } from "react";
import { notFound } from "next/navigation";

import { ChatInterface } from "@/components/chat/chat-interface";
import { ConversationLayout } from "@/components/layout/conversation-layout";
import { Skeleton } from "@/components/ui/skeleton";

type ChatConversationPageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function ChatConversationPage({ params }: ChatConversationPageProps) {
  const { id } = await params;

  if (!id?.trim()) {
    notFound();
  }

  return (
    <ConversationLayout>
      <Suspense
        fallback={
          <div className="flex flex-1 flex-col gap-4 py-8">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="h-24 w-full" />
          </div>
        }
      >
        <ChatInterface conversationId={id} />
      </Suspense>
    </ConversationLayout>
  );
}
