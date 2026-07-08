"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { isConversationActive } from "@/lib/navigation";
import type { ConversationRecord } from "@/lib/conversations/types";
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

  const [menuOpen, setMenuOpen] = useState(false);
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
    setMenuOpen(false);
  };

  const handleDelete = () => {
    setMenuOpen(false);
    const confirmed = window.confirm(`Delete "${conversation.title}"? This cannot be undone.`);
    if (!confirmed) return;

    onDelete(conversation.id);
    if (active) {
      router.push("/chat");
    }
  };

  if (isEditing) {
    return (
      <div className="rounded-lg px-2 py-1.5">
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
        "group relative flex items-center rounded-lg transition-colors",
        active
          ? "border-l-2 border-primary bg-sidebar-accent text-sidebar-accent-foreground"
          : "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
      )}
    >
      <Link
        href={href}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        title={conversation.title}
        className={cn("min-w-0 flex-1 px-3 py-2", active && "pl-[10px]")}
      >
        <span className="block truncate text-sm font-medium">{conversation.title}</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">{relativeTime}</span>
      </Link>

      <div className="relative pr-1">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-7 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
          aria-label="Conversation options"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <MoreHorizontal className="size-4" />
        </Button>

        {menuOpen ? (
          <>
            <button
              type="button"
              className="fixed inset-0 z-40 cursor-default"
              aria-label="Close menu"
              onClick={() => setMenuOpen(false)}
            />
            <div
              role="menu"
              className="absolute right-0 top-full z-50 mt-1 w-36 rounded-lg border border-border bg-popover py-1 shadow-md"
            >
              <button
                type="button"
                role="menuitem"
                className="flex w-full items-center gap-2 px-3 py-1.5 text-sm hover:bg-muted"
                onClick={() => {
                  setMenuOpen(false);
                  setIsEditing(true);
                }}
              >
                <Pencil className="size-3.5" />
                Rename
              </button>
              <button
                type="button"
                role="menuitem"
                className="flex w-full items-center gap-2 px-3 py-1.5 text-sm text-destructive hover:bg-muted"
                onClick={handleDelete}
              >
                <Trash2 className="size-3.5" />
                Delete
              </button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
