import { Suspense } from "react";

import { NewChatRedirect } from "@/components/chat/new-chat-redirect";
import { ConversationLayout } from "@/components/layout/conversation-layout";
import { Skeleton } from "@/components/ui/skeleton";

function ChatLoadingFallback() {
  return (
    <div className="flex flex-1 flex-col gap-4 py-8">
      <Skeleton className="h-8 w-2/3" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

export default function ChatPage() {
  return (
    <ConversationLayout>
      <Suspense fallback={<ChatLoadingFallback />}>
        <NewChatRedirect />
      </Suspense>
    </ConversationLayout>
  );
}
