"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Menu } from "@base-ui/react/menu";
import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { isConversationActive } from "@/lib/navigation";
import type { ConversationRecord } from "@/lib/conversations/types";
import { listConversations } from "@/lib/conversations/storage";
import { formatRelativeTime } from "@/lib/time/relative";
import { cn } from "@/lib/utils";

type ConversationItemProps = {
  conversation: ConversationRecord;
  onNavigate?: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
};

export function ConversationItem({
  conversation,
  onNavigate,
  onRename,
  onDelete,
}: ConversationItemProps) {
  const pathname = usePathname();
  const router = useRouter();
  const active = isConversationActive(pathname, conversation.id);
  const href = `/chat/${conversation.id}`;
  const relativeTime = formatRelativeTime(conversation.updatedAt);

  const [isEditing, setIsEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(conversation.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isEditing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [isEditing]);

  useEffect(() => {
    setDraftTitle(conversation.title);
  }, [conversation.title]);

  const commitRename = () => {
    const trimmed = draftTitle.trim();
    if (trimmed && trimmed !== conversation.title) {
      onRename(conversation.id, trimmed);
    } else {
      setDraftTitle(conversation.title);
    }
    setIsEditing(false);
  };

  const handleDelete = () => {
    const confirmed = window.confirm(`Delete "${conversation.title}"? This cannot be undone.`);
    if (!confirmed) return;

    const wasActive = active;
    onDelete(conversation.id);

    if (!wasActive) return;

    // Stay on history — open the next remaining chat, or an empty canvas.
    // Do not auto-create a replacement "New chat" entry.
    const next = listConversations()[0];
    router.replace(next ? `/chat/${next.id}` : "/chat");
  };

  if (isEditing) {
    return (
      <div className="rounded-md px-2 py-1.5">
        <Input
          ref={inputRef}
          value={draftTitle}
          onChange={(e) => setDraftTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitRename();
            if (e.key === "Escape") {
              setDraftTitle(conversation.title);
              setIsEditing(false);
            }
          }}
          onBlur={commitRename}
          className="h-8 text-sm"
          aria-label="Rename conversation"
        />
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group relative flex items-center rounded-md transition-colors",
        active
          ? "border-l-2 border-sidebar-primary bg-sidebar-accent text-sidebar-accent-foreground"
          : "text-sidebar-foreground/75 hover:bg-sidebar-accent/70 hover:text-sidebar-foreground",
      )}
    >
      <Link
        href={href}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        title={conversation.title}
        className={cn("min-w-0 flex-1 rounded-md px-3 py-1.5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sidebar-ring", active && "pl-[10px]")}
      >
        <span className="block truncate text-sm font-medium">{conversation.title}</span>
        <span className="mt-0.5 block text-[11px] text-muted-foreground">{relativeTime}</span>
      </Link>

      <div className="relative pr-1">
        <Menu.Root>
          <Menu.Trigger
            render={
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-10 text-muted-foreground opacity-100 hover:text-sidebar-foreground md:size-7 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100"
                aria-label="Conversation options"
              >
                <MoreHorizontal className="size-4" />
              </Button>
            }
          />
          <Menu.Portal>
            <Menu.Positioner side="bottom" align="end" sideOffset={4} className="z-50">
              <Menu.Popup className="w-36 rounded-md border border-border bg-popover py-1 shadow-sm outline-none">
                <Menu.Item
                  className="flex cursor-default items-center gap-2 px-3 py-1.5 text-sm outline-none data-highlighted:bg-muted"
                  onClick={() => setIsEditing(true)}
                >
                  <Pencil className="size-3.5" />
                  Rename
                </Menu.Item>
                <Menu.Item
                  className="flex cursor-default items-center gap-2 px-3 py-1.5 text-sm text-destructive outline-none data-highlighted:bg-muted"
                  onClick={handleDelete}
                >
                  <Trash2 className="size-3.5" />
                  Delete
                </Menu.Item>
              </Menu.Popup>
            </Menu.Positioner>
          </Menu.Portal>
        </Menu.Root>
      </div>
    </div>
  );
}
