"use client";

import Link from "next/link";
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Files, MessageSquarePlus, PanelLeftClose, PanelLeftOpen, Search, X } from "lucide-react";

import { ConversationItem } from "@/components/layout/conversation-item";
import { UtilityNavLink } from "@/components/layout/utility-nav-link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useConversations } from "@/lib/hooks/use-conversations";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";
import { isUtilityNavActive, utilityNavItems } from "@/lib/navigation";
import { chatCopy } from "@/lib/user-language";
import { cn } from "@/lib/utils";
import { useServerConversations } from "@/components/providers/server-conversations-provider";
import type { ConversationGroup } from "@/lib/conversations/types";
import { DEMO_MODE } from "@/lib/demo";
import { ConversationCreationRecovery } from "@/components/chat/conversation-creation-recovery";

type ConversationSidebarProps = {
  className?: string;
  onNavigate?: () => void;
  collapsible?: boolean;
};

export function ConversationSidebar(props: ConversationSidebarProps) {
  return DEMO_MODE ? <DemoSidebar {...props} /> : <ServerSidebar {...props} />;
}

function DemoSidebar(props: ConversationSidebarProps) {
  const router = useRouter();
  const local = useConversations();
  const pathname = usePathname();
  return <SidebarView {...props} groups={local.groups} isLoading={local.isLoading}
    error={local.storageError} onNew={async () => {
      try { const created = local.startNewConversation(); props.onNavigate?.(); router.push(`/chat/${created.id}`); } catch { /* Hook exposes safe error. */ }
    }} onRename={local.renameConversation} onDelete={(id) => {
      local.removeConversation(id);
      if (pathname === `/chat/${id}`) {
        const next = local.conversations.find(row => row.id !== id);
        router.replace(next ? `/chat/${next.id}` : "/chat");
      }
    }} />;
}

function ServerSidebar(props: ConversationSidebarProps) {
  const { state, controller, creationDraft } = useServerConversations();
  const router = useRouter();
  const pathname = usePathname();
  // The mobile sheet is modal; otherwise Chat owns the primary recovery action.
  const showRecovery = !!props.onNavigate || !(pathname === "/chat" || pathname.startsWith("/chat/"));
  const groups: ConversationGroup[] = [{ label: "Recent", conversations: state.conversations.map(row => ({
    id: row.id, title: row.title, createdAt: row.created_at, updatedAt: row.last_activity_at,
  })) }];
  return <SidebarView {...props} key={`${state.ownerId}:${state.sessionRevision}`} groups={groups}
    isLoading={state.listLoading} error={showRecovery ? state.error?.message ?? null : null} disabled={!state.ownerId || !!state.creation}
    creating={!!state.creation && !state.creation.uncertain}
    onNew={async () => { const row = await controller.create(); if (row && controller.getSnapshot().selectedId === row.id) { props.onNavigate?.(); router.push(`/chat/${row.id}`); } }}
    onRename={(id, title) => { void controller.rename(id, title); }}
    onDelete={(id) => { void controller.delete(id).then(confirmed => {
      if (confirmed && controller.getSnapshot().ownerId === state.ownerId && controller.getSnapshot().sessionRevision === state.sessionRevision && controller.getSnapshot().selectedId === null)
        router.replace("/chat");
    }); }}
    onRefresh={() => { void controller.refreshList(); }}
    onMore={state.nextListCursor ? () => { void controller.loadMoreConversations(); } : undefined}
    onReconcileCreation={state.creation?.uncertain && showRecovery ? () => {
      // Registration delegates recovery, not ownership of the creation's draft.
      if (creationDraft.reconcile()) return;
      const pending = controller.getSnapshot().creation;
      if (!pending) return;
      // With no originating composer, recover history without changing selection
      // or navigating away from the user's intentional destination.
      void controller.retryCreate({ requestId: pending.requestId, select: false });
    } : undefined}
  />;
}

function SidebarView({ className, onNavigate, collapsible = false, groups, isLoading, error,
  onNew, onRename, onDelete, onRefresh, onMore, onReconcileCreation, disabled = false, creating = false,
}: ConversationSidebarProps & {
  groups: ConversationGroup[]; isLoading: boolean; error: string | null;
  onNew: () => Promise<void>; onRename: (id: string, title: string) => unknown; onDelete: (id: string) => void;
  onRefresh?: () => void; onMore?: () => void; onReconcileCreation?: () => void; disabled?: boolean; creating?: boolean;
}) {
  const { needsConnect, isReady, setupState, fileStats, error: knowledgeError } = useKnowledgeStatus({ pollIntervalMs: 30_000 });
  const [chatQuery, setChatQuery] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const compact = collapsible && collapsed;
  const focusAfterReview = useRef(false);
  const collapseButton = useRef<HTMLButtonElement>(null);
  const feedbackContainer = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (compact || !focusAfterReview.current) return;
    focusAfterReview.current = false;
    // Only Review requests this handoff, after the expanded controls mount.
    const destination = feedbackContainer.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")
      ?? collapseButton.current;
    if (destination?.isConnected && !destination.disabled) destination.focus();
  }, [compact]);

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

  const showSetupChip = !DEMO_MODE;
  const hasChats = groups.some((g) => g.conversations.length > 0);
  const hasFilteredChats = filteredGroups.some((g) => g.conversations.length > 0);
  const isSearching = chatQuery.trim().length > 0;
  const searchLabel = DEMO_MODE ? chatCopy.searchChatsPlaceholder : "Search loaded chats";
  const feedback = onReconcileCreation ? <ConversationCreationRecovery error={error} onRecover={onReconcileCreation} />
    : error ? <p role="alert" className="text-sm break-words">{error}</p> : null;

  return (
    <aside
      className={cn(
        "flex h-full shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground",
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
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <p className="truncate text-sm font-semibold tracking-tight text-sidebar-foreground">DriveMind AI</p>
            {DEMO_MODE ? <span className="shrink-0 rounded-md bg-sidebar-accent px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">Demo</span> : null}
          </div>
        ) : null}
        {collapsible ? (
          <Button
            ref={collapseButton}
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={compact ? "Expand sidebar" : "Collapse sidebar"}
            title={compact ? "Expand sidebar" : "Collapse sidebar"}
            className="text-muted-foreground hover:text-sidebar-foreground"
            onClick={() => setCollapsed((value) => !value)}
          >
            {compact ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
          </Button>
        ) : null}
      </div>

      <div className={cn("flex shrink-0 flex-col gap-2 pb-3", compact ? "px-2" : "px-3")}>
        <button
          type="button"
          onClick={() => void onNew()}
          disabled={disabled || isLoading}
          aria-label={creating ? "Creating chat…" : "New Chat"}
          aria-busy={creating || undefined}
          title={compact ? creating ? "Creating chat…" : "New Chat" : undefined}
          className={cn(
            "flex w-full items-center gap-2 rounded-lg bg-primary py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring active:translate-y-px",
            compact ? "justify-center px-2" : "px-3",
          )}
        >
          <MessageSquarePlus className="size-4 shrink-0" />
          {!compact ? creating ? <span role="status">Creating chat…</span> : "New Chat" : null}
        </button>
      </div>

      {!compact ? <Separator /> : null}

      {DEMO_MODE && feedback ? <div className="p-3">{feedback}</div> : null}
      {!DEMO_MODE && compact && feedback ? <div className="px-1 py-2">
        <span role="alert" className="sr-only">{onReconcileCreation ? "Recover the pending chat before starting another." : error}</span>
        <Button variant="ghost" className="w-full px-0 text-xs" aria-label="Expand sidebar to review chat status" onClick={() => { focusAfterReview.current = true; setCollapsed(false); }}>Review</Button>
      </div> : null}
      {/* Chat history */}
      {!compact ? <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="shrink-0 space-y-2 px-3 pt-3 pb-2">
          <div className="flex items-center justify-between gap-2">
            {DEMO_MODE ? <p className="text-xs font-medium text-muted-foreground">{chatCopy.recentChats}</p>
              : <h2 className="text-xs font-medium text-muted-foreground">Chats</h2>}
            {onRefresh ? <Button type="button" variant="ghost" size="sm" aria-label="Refresh conversations" disabled={isLoading}
              className="text-xs text-muted-foreground" onClick={onRefresh}>Refresh</Button> : null}
          </div>

          {hasChats ? (
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={chatQuery}
                onChange={(event) => setChatQuery(event.target.value)}
                placeholder={searchLabel}
                className="h-8 border-sidebar-border bg-card/70 pl-8 pr-8 text-xs"
                aria-label={searchLabel}
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

        {!DEMO_MODE && feedback ? <div ref={feedbackContainer} className="max-h-[35vh] shrink-0 overflow-y-auto overscroll-contain px-3 pb-3">{feedback}</div> : null}

        <nav
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-3"
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
              <div key={group.label} className="mb-4">
                {DEMO_MODE ? <p className="px-2 pb-1.5 text-[11px] font-medium text-muted-foreground">
                  {group.label}
                </p> : null}
                <div className="space-y-0.5">
                  {group.conversations.map((conversation) => (
                    <ConversationItem
                      key={conversation.id}
                      conversation={conversation}
                      onNavigate={onNavigate}
                      onRename={(id, title) => onRename(id, title)}
                      onDelete={onDelete}
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
          {onMore ? <Button variant="ghost" disabled={isLoading} onClick={onMore}>Load more conversations</Button> : null}
        </nav>
      </div> : <div className="min-h-0 flex-1" />}

      <Separator />

      {/* Primary + utility nav */}
      <nav
        className={cn("flex shrink-0 flex-col gap-0.5", compact ? "px-2 pt-2" : "px-3 pt-2.5 pb-1")}
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
        className={cn("flex shrink-0 flex-col gap-0.5 pb-3", compact ? "px-2" : "px-3")}
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
          <div className="space-y-1 text-sm">
            <p role="status" className="text-muted-foreground">
              {setupState === "checking" ? "Checking prepared documents…" : knowledgeError ? "Knowledge status unavailable"
                : isReady ? `${fileStats.indexed} ${fileStats.indexed === 1 ? "document ready" : "documents ready"}`
                  : needsConnect ? "Connect Drive to choose documents" : "Prepare documents to start chatting"}
            </p>
            {!isReady ? <Link href={needsConnect ? "/onboarding" : "/files"} onClick={onNavigate}
              className="inline-flex min-h-11 items-center underline underline-offset-4">
              {needsConnect ? "Connect Google Drive" : "Browse files"}
            </Link> : null}
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
  const pathname = usePathname();
  const active = isUtilityNavActive(pathname, href);

  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      title={compact ? label : undefined}
      className={cn(
        "flex items-center rounded-md py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sidebar-ring",
        compact ? "justify-center px-2" : "gap-3 px-3",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground"
          : "text-sidebar-foreground/75 hover:bg-sidebar-accent/70 hover:text-sidebar-foreground",
      )}
    >
      <div className="flex size-6 shrink-0 items-center justify-center">
        <Icon className="size-4" />
      </div>
      {!compact ? <span className="truncate">{label}</span> : null}
    </Link>
  );
}
