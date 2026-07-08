"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Skeleton } from "@/components/ui/skeleton";
import { createConversation } from "@/lib/conversations/storage";

/** `/chat` always opens a fresh conversation thread. */
export function NewChatRedirect() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const conversation = createConversation();
    const ask = searchParams.get("ask");
    const query = ask ? `?ask=${encodeURIComponent(ask)}` : "";
    router.replace(`/chat/${conversation.id}${query}`);
  }, [router, searchParams]);

  return (
    <div className="flex flex-1 flex-col gap-4 py-8">
      <Skeleton className="h-8 w-2/3" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}
