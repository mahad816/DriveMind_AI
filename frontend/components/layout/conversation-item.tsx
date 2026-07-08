"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isConversationActive } from "@/lib/navigation";
import type { ConversationRecord } from "@/lib/conversations/types";
import { formatRelativeTime } from "@/lib/time/relative";
import { cn } from "@/lib/utils";

type ConversationItemProps = {
  conversation: ConversationRecord;
  onNavigate?: () => void;
};

export function ConversationItem({ conversation, onNavigate }: ConversationItemProps) {
  const pathname = usePathname();
  const active = isConversationActive(pathname, conversation.id);
  const href = `/chat/${conversation.id}`;
  const relativeTime = formatRelativeTime(conversation.updatedAt);

  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      title={conversation.title}
      className={cn(
        "block rounded-lg px-3 py-2 transition-colors",
        active
          ? "border-l-2 border-primary bg-sidebar-accent pl-[10px] text-sidebar-accent-foreground"
          : "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
      )}
    >
      <span className="block truncate text-sm font-medium">{conversation.title}</span>
      <span className="mt-0.5 block text-xs text-muted-foreground">{relativeTime}</span>
    </Link>
  );
}
