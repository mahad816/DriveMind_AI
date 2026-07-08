"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Files, MessageSquare, MessageSquarePlus } from "lucide-react";

import { ConversationItem } from "@/components/layout/conversation-item";
import { UtilityNavLink } from "@/components/layout/utility-nav-link";
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
};

export function ConversationSidebar({ className, onNavigate }: ConversationSidebarProps) {
  const router = useRouter();
  const { needsConnect, needsPrepare } = useKnowledgeStatus({ pollIntervalMs: 30_000 });
  const { groups, isLoading, startNewConversation, renameConversation, removeConversation } =
    useConversations();

  const handleNewChat = () => {
    const created = startNewConversation();
    onNavigate?.();
    router.push(`/chat/${created.id}`);
  };

  const showSetupChip = needsConnect || needsPrepare;
  const hasChats = groups.some((g) => g.conversations.length > 0);

  return (
    <aside
      className={cn(
        "flex h-full w-[240px] shrink-0 flex-col border-r border-border bg-sidebar text-sidebar-foreground",
        className,
      )}
      aria-label="App navigation"
    >
      {/* Logo */}
      <div className="flex h-14 shrink-0 items-center gap-2.5 px-4">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <MessageSquare className="size-4" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold tracking-tight">DriveMind AI</p>
          <p className="truncate text-xs text-muted-foreground">Your knowledge OS</p>
        </div>
      </div>

      <div className="flex shrink-0 flex-col gap-1 px-3 pb-3">
        <button
          type="button"
          onClick={handleNewChat}
          className="flex w-full items-center gap-2 rounded-xl border border-primary/30 bg-primary/10 px-3 py-2.5 text-sm font-medium text-primary transition-colors hover:bg-primary/20"
        >
          <MessageSquarePlus className="size-4 shrink-0" />
          New Chat
        </button>
      </div>

      <Separator />

      {/* Chat history */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="px-3 pt-3 pb-1">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {chatCopy.recentChats}
          </p>
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
          ) : hasChats ? (
            groups.map((group) => (
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
          ) : (
            <p className="px-3 py-2 text-xs text-muted-foreground">{chatCopy.noChatsYet}</p>
          )}
        </nav>
      </div>

      <Separator />

      {/* Primary + utility nav */}
      <nav className="flex shrink-0 flex-col gap-0.5 p-3" aria-label="Primary navigation">
        <PrimaryNavLink
          href="/files"
          icon={Files}
          label="Files"
          description="Your knowledge library"
          onNavigate={onNavigate}
        />
      </nav>

      <nav className="flex shrink-0 flex-col gap-1 px-3 pb-3" aria-label="Utility navigation">
        {utilityNavItems
          .filter((item) => item.href !== "/files")
          .map((item) => (
            <UtilityNavLink key={item.href} item={item} onNavigate={onNavigate} />
          ))}
      </nav>

      {showSetupChip ? (
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
  description?: string;
  onNavigate?: () => void;
};

function PrimaryNavLink({ href, icon: Icon, label, description, onNavigate }: PrimaryNavLinkProps) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      className="flex items-center gap-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
    >
      <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        <Icon className="size-4" />
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-foreground">{label}</p>
        {description ? (
          <p className="truncate text-xs text-muted-foreground">{description}</p>
        ) : null}
      </div>
    </Link>
  );
}
