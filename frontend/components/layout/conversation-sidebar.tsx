"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Files, MessageSquare, MessageSquarePlus, PanelLeftClose, PanelLeftOpen, Search, X } from "lucide-react";

import { ConversationItem } from "@/components/layout/conversation-item";
import { UtilityNavLink } from "@/components/layout/utility-nav-link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useConversations } from "@/lib/hooks/use-conversations";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";
import { utilityNavItems } from "@/lib/navigation";
import { chatCopy, knowledgeStatusLabel } from "@/lib/user-language";
import { cn } from "@/lib/utils";

type ConversationSidebarProps = {
  className?: string;
  onNavigate?: () => void;
  collapsible?: boolean;
};

export function ConversationSidebar({ className, onNavigate, collapsible = true }: ConversationSidebarProps) {
  const router = useRouter();
  const { needsConnect, needsPrepare } = useKnowledgeStatus({ pollIntervalMs: 30_000 });
  const { groups, isLoading, startNewConversation, renameConversation, removeConversation } =
    useConversations();
  const [chatQuery, setChatQuery] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const compact = collapsible && collapsed;

  const handleNewChat = () => {
    const created = startNewConversation();
    onNavigate?.();
    router.push(`/chat/${created.id}`);
  };

  const filteredGroups = useMemo(() => {
    const q = chatQuery.trim().toLowerCase();
    if (!q) return groups;

    return groups
      .map((group) => ({
        ...group,
        conversations: group.conversations.filter((conversation) =>
          conversation.title.toLowerCase().includes(q),
        ),
      }))
      .filter((group) => group.conversations.length > 0);
  }, [chatQuery, groups]);

  const showSetupChip = needsConnect || needsPrepare;
  const hasChats = groups.some((g) => g.conversations.length > 0);
  const hasFilteredChats = filteredGroups.some((g) => g.conversations.length > 0);
  const isSearching = chatQuery.trim().length > 0;

  return (
    <aside
      className={cn(
        "flex h-full shrink-0 flex-col border-r border-border bg-sidebar text-sidebar-foreground",
        compact ? "w-16" : "w-[260px]",
        className,
      )}
      aria-label="App navigation"
    >
      <div
        className={cn(
          "flex h-14 shrink-0 items-center gap-2.5",
          compact ? "justify-center px-2" : "px-4",
        )}
      >
        {!compact ? (
          <>
            <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <MessageSquare className="size-4" />
            </div>
            <p className="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight">DriveMind AI</p>
          </>
        ) : null}
        {collapsible ? (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={compact ? "Expand sidebar" : "Collapse sidebar"}
            title={compact ? "Expand sidebar" : "Collapse sidebar"}
            onClick={() => setCollapsed((value) => !value)}
          >
            {compact ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
          </Button>
        ) : null}
      </div>

      <div className={cn("flex shrink-0 flex-col gap-2 pb-3", compact ? "px-2" : "px-3")}>
        <button
          type="button"
          onClick={handleNewChat}
          aria-label="New Chat"
          title={compact ? "New Chat" : undefined}
          className={cn(
            "flex w-full items-center gap-2 rounded-xl border border-primary/30 bg-primary/10 py-2.5 text-sm font-medium text-primary transition-colors hover:bg-primary/20",
            compact ? "justify-center px-2" : "px-3",
          )}
        >
          <MessageSquarePlus className="size-4 shrink-0" />
          {!compact ? "New Chat" : null}
        </button>
      </div>

      {!compact ? <Separator /> : null}

      {/* Chat history */}
      {!compact ? <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="space-y-2 px-3 pt-3 pb-1">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {chatCopy.recentChats}
          </p>

          {hasChats ? (
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={chatQuery}
                onChange={(event) => setChatQuery(event.target.value)}
                placeholder={chatCopy.searchChatsPlaceholder}
                className="h-8 border-border/70 bg-background/60 pl-8 pr-8 text-xs"
                aria-label={chatCopy.searchChatsPlaceholder}
              />
              {chatQuery ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="absolute top-1/2 right-0.5 size-7 -translate-y-1/2 text-muted-foreground"
                  onClick={() => setChatQuery("")}
                  aria-label="Clear search"
                >
                  <X className="size-3.5" />
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>

        <nav
          className="min-h-0 flex-1 overflow-y-auto px-2 pb-2"
          aria-label="Recent conversations"
        >
          {isLoading ? (
            <div className="space-y-2 px-1">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : hasFilteredChats ? (
            filteredGroups.map((group) => (
              <div key={group.label} className="mb-3">
                <p className="px-2 pb-1 text-[11px] font-medium text-muted-foreground">
                  {group.label}
                </p>
                <div className="space-y-0.5">
                  {group.conversations.map((conversation) => (
                    <ConversationItem
                      key={conversation.id}
                      conversation={conversation}
                      onNavigate={onNavigate}
                      onRename={(id, title) => renameConversation(id, title)}
                      onDelete={removeConversation}
                    />
                  ))}
                </div>
              </div>
            ))
          ) : hasChats && isSearching ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">{chatCopy.noChatsMatch}</p>
          ) : (
            <p className="px-3 py-2 text-xs text-muted-foreground">{chatCopy.noChatsYet}</p>
          )}
        </nav>
      </div> : <div className="min-h-0 flex-1" />}

      <Separator />

      {/* Primary + utility nav */}
      <nav
        className={cn("flex shrink-0 flex-col gap-0.5", compact ? "px-2 pt-2" : "p-3")}
        aria-label="Primary navigation"
      >
        <PrimaryNavLink
          href="/files"
          icon={Files}
          label="Files"
          compact={compact}
          onNavigate={onNavigate}
        />
      </nav>

      <nav
        className={cn("flex shrink-0 flex-col gap-1 pb-3", compact ? "px-2" : "px-3")}
        aria-label="Utility navigation"
      >
        {utilityNavItems
          .filter((item) => item.href !== "/files")
          .map((item) => (
            <UtilityNavLink
              key={item.href}
              item={item}
              onNavigate={onNavigate}
              compact={compact}
            />
          ))}
      </nav>

      {showSetupChip && !compact ? (
        <div className="shrink-0 border-t border-sidebar-border p-3">
          <div className="rounded-xl border border-warning/30 bg-warning/10 p-3 text-xs">
            <p className="font-medium text-foreground">
              {needsConnect ? "Connect Google Drive" : "Your assistant isn't ready yet"}
            </p>
            <Link
              href={needsConnect ? "/onboarding" : "/index"}
              onClick={onNavigate}
              className="mt-1 inline-block text-primary underline underline-offset-2"
            >
              {needsConnect ? "Get started →" : `${knowledgeStatusLabel.setup} →`}
            </Link>
          </div>
        </div>
      ) : null}
    </aside>
  );
}

type PrimaryNavLinkProps = {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  compact?: boolean;
  onNavigate?: () => void;
};

function PrimaryNavLink({ href, icon: Icon, label, compact = false, onNavigate }: PrimaryNavLinkProps) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-label={label}
      title={compact ? label : undefined}
      className={cn(
        "flex items-center rounded-xl py-2.5 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        compact ? "justify-center px-2" : "gap-3 px-3",
      )}
    >
      <div
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground",
          !compact && "bg-muted",
        )}
      >
        <Icon className="size-4" />
      </div>
      {!compact ? <span className="truncate text-sm font-medium text-foreground">{label}</span> : null}
    </Link>
  );
}
